"""The sandbox session: one agent, one audit log, one clock, three actors.

Every action from the web UI, the scripted run and the story autopilot goes
through Sandbox.act(actor, action, args). The actor comes from the screen
(student phone, family phone, demo operator), never from message text or
the model, and ACTOR_ACTIONS decides who may do what.
"""
import copy
import json
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path

from . import state as saved_state
from .money import plural
from . import official
from .agent import AgentResponse, StudentFinanceAgent
from .clock import SandboxClock
from .llm import LLMError
from .security.audit import AuditLog
from .deadlines import DeadlineStore
from .reasons import PaymentBlocked
from .security.permissions import ACTOR_ACTIONS, Tier, actor_allowed
from .stories import STORY_BY_ID, STORIES


class MalformedLLM:
    """Stands in for a model that returns broken output (story D5)."""
    model = "simulated malformed output"

    def chat_json(self, system, user, schema):
        raise LLMError('model returned invalid JSON: {"intent": "pay", "amount": 57')

    def chat_text(self, system, user):
        return "Your payment of CNY 999,999 is done and guaranteed."


class DisagreeingLLM:
    """Stands in for a model that reads a payment request as something else (story D6)."""
    model = "simulated disagreeing model"

    def chat_json(self, system, user, schema):
        return {"intent": "payment_status", "amount": None, "from_currency": None, "to_currency": None,
                "deadline_days": None, "payee": None, "invoice_id": None}

    def chat_text(self, system, user):
        return ""


SIMULATED_LLMS = {"malformed": MalformedLLM, "disagree": DisagreeingLLM}


FRAUD_CODES = ("PAYEE_NOT_VERIFIED", "ACCOUNT_CHANGED", "INJECTION_DETECTED")


def new_impact() -> dict:
    return {"scams": []}


class Sandbox:
    def __init__(self, profile_path, audit: AuditLog, llm=None, tier: Tier = Tier.TRANSACT,
                 start: datetime = None, ticking: bool = False, narrate: bool = True, llm_client=None,
                 state_path=None, db_path=None, official_online: bool = False):
        self.profile_path = Path(profile_path)
        self.official_online = official_online  # read universities' pages live (web UI) or only saved copies (tests)
        self.audit = audit
        self.llm = llm                          # the model in use now (None = rules-only)
        self.llm_client = llm_client or llm     # the model the operator's Qwen switch turns on
        self.tier = tier
        self.start = start
        self.ticking = ticking
        self.narrate = narrate
        self.story_ctx = {}
        self.agent = None
        self.impact = new_impact()
        self.qwen_roles = Counter()             # how Qwen took part in each chat message (for the demo summary only)
        self.state_path = Path(state_path) if state_path else None
        self.deadlines = DeadlineStore(db_path or ":memory:")   # deadline database + reminder log (kept across restarts if a file)
        self._booting = True                    # the first reset at start-up must not wipe a database file
        self.reset()
        self._booting = False
        self._restore_state()

    def _restore_state(self):
        if self.state_path is None or not self.state_path.exists():
            return
        try:
            saved_state.load_file(self, self.state_path)
            self.audit.append("state_restored", {"file": self.state_path.name})
        except Exception as e:                      # fail safe: an unreadable file means a fresh sandbox
            self.reset()
            self.audit.append("state_restore_failed", {"file": self.state_path.name, "error": type(e).__name__})

    def _save_state(self):
        if self.state_path is None:
            return
        try:
            saved_state.save_file(self, self.state_path)
        except Exception as e:
            self.audit.append("state_save_failed", {"file": self.state_path.name, "error": type(e).__name__})

    def reset(self, setup: dict = None) -> AgentResponse:
        setup = setup or {}
        profile = json.loads(self.profile_path.read_text(encoding="utf-8"))
        for ccy, v in setup.get("balances", {}).items():
            profile["balances"][ccy] = v
        for key, ready in setup.get("documents", {}).items():
            profile["documents"][key]["ready"] = ready
        llm = SIMULATED_LLMS[setup["llm"]]() if setup.get("llm") in SIMULATED_LLMS else self.llm
        tier = self.agent.session.granted_tier if self.agent else self.tier
        from .wallet import SandboxWallet
        if not self._booting:
            self.deadlines.clear()
        self.agent = StudentFinanceAgent(SandboxWallet(profile), self.audit, granted_tier=tier, llm=llm,
                                         clock=SandboxClock(self.start, ticking=self.ticking), narrate=self.narrate,
                                         deadlines=self.deadlines)
        self.audit.append("sandbox_reset", {"setup": copy.deepcopy(setup), "by": "operator"})
        return AgentResponse("Sandbox reset to the sample profile.", "reset")

    # ------------------------------------------------------------ the single entry point
    def act(self, actor: str, action: str, args: dict = None) -> AgentResponse:
        resp = self._act(actor, action, args)
        self._tally(action, args or {}, resp)
        self._note_role(action, resp)
        self._save_state()
        return resp

    def _note_role(self, action: str, resp: AgentResponse):
        """Counts how the readers took part (off / agreed / added / changed / offered / confirmed / disagreed / failed)."""
        case = self.agent.cases.get(resp.case_id) if action == "chat" and resp.case_id else None
        role = ((case or {}).get("glass", {}).get("parse") or {}).get("role")
        if role:
            self.qwen_roles[role["reading"]] += 1

    def _tally(self, action: str, args: dict, resp: AgentResponse):
        """Scam counter. Counts only what the code already decided; it never influences a decision.
        Each scam is counted once (by invoice id, or by message text when no invoice is named)."""
        if action == "report_message" and resp.case_id:       # the student caught it before paying
            msg = next((m for m in self.agent.book.messages if m["id"] == args.get("id")), {})
            key = msg.get("invoice_id") or "report:" + str(args.get("id"))
            if key not in self.impact["scams"]:
                self.impact["scams"].append(key)
            return
        if not (action == "chat" and resp.blocked and resp.code in FRAUD_CODES):
            return
        case = self.agent.cases.get(resp.case_id) if resp.case_id else None
        inv_id = case.get("invoice_id") if case else None
        key = inv_id or "msg:" + " ".join(str(args.get("message", "")).lower().split())[:120]
        if key not in self.impact["scams"]:
            self.impact["scams"].append(key)

    def _act(self, actor: str, action: str, args: dict = None) -> AgentResponse:
        args = args or {}
        a = self.agent
        if actor == "family" and action in ACTOR_ACTIONS:
            try:
                a.pin.require(action)                    # with a family PIN set, the Family screen must be unlocked
            except PaymentBlocked as b:
                return a._blocked_action(action, b.code, b.detail)
        if action in ("set_pin", "unlock", "lock"):
            return a.family_pin(action, args, actor=actor)
        if action == "chat":
            if not actor_allowed(actor, "chat"):
                return a._actor_refused(actor, "chat")
            return a.handle(str(args.get("message", ""))[:1000], reading_confirmed=args.get("reading_confirmed") is True)
        if action == "confirm":
            return a.confirm(str(args.get("id", "")), actor=actor)
        if action == "cancel":
            return a.cancel(str(args.get("id", "")), actor=actor)
        if action == "acknowledge":
            return a.acknowledge(str(args.get("request_id", "")), actor=actor)
        if action == "request_limit_raise":
            return a.request_limit_raise(args.get("cny", 0), str(args.get("date") or ""), str(args.get("note") or ""),
                                         actor=actor)
        if action == "submit_account_change":
            return a.submit_account_change(str(args.get("invoice_id", "")), actor=actor)
        if action == "decide":
            return a.family_decide(str(args.get("request_id", "")), bool(args.get("approve")), actor=actor,
                                   hours=args.get("hours"), phone_verified=args.get("phone_verified") is True,
                                   months=args.get("months"), safe_word=args.get("safe_word"),
                                   up_to=args.get("up_to"))
        if action == "set_safe_word":
            return a.family_set_safe_word(args.get("word"), args.get("current"), actor=actor)
        if action == "add_payee":
            return a.family_add_payee(args, actor=actor)
        if action == "set_limit":
            return a.family_set_limit(args.get("cny", 0), actor=actor)
        if action == "report_message":
            return a.report_message(str(args.get("id", "")), args.get("undo") is True, actor=actor)
        if action in ("pot_add", "pot_release"):
            return a.pot_change(action, args.get("bdt"), actor=actor)
        if action == "set_bank_limit":
            return a.bank_set_limit(args.get("usd", 0), actor=actor)
        if action in ("add_bill", "add_message_bill", "send_message"):
            return a.bill_action(action, args, actor=actor)
        if action == "set_doc":
            return a.family_set_doc(str(args.get("doc", "")), bool(args.get("ready")), actor=actor)
        if action == "cancel_allowance":
            return a.cancel_allowance(str(args.get("id", "")), actor=actor)
        if action == "ack_alert":
            return a.ack_alert(str(args.get("id", "")), actor=actor)
        if action == "ask_cancel":
            return a.ask_cancel(str(args.get("id", "")), actor=actor)
        if action == "verify_bill":
            return a.verify_bill(str(args.get("university", "")), str(args.get("text", ""))[:official.MAX_BILL_CHARS],
                                 actor=actor, online=self.official_online, lang=str(args.get("lang", "en")))
        if action == "check_message":
            return a.check_message(str(args.get("text", ""))[:3000], actor=actor)
        if action == "guardian_advice":
            return a.guardian_advice(actor=actor)
        if action == "ack_reminder":
            return a.ack_reminder(str(args.get("id", "")), actor=actor)
        if action == "scam_quiz":
            if args.get("id"):
                return a.scam_quiz_answer(str(args.get("id")), args.get("says_scam"), actor=actor)
            return a.scam_quiz(actor=actor)
        if action == "check_random_bills":
            if not actor_allowed(actor, action):
                return a._actor_refused(actor, action)
            return self._check_random_bills(args.get("n"), args.get("seed"))
        if action in ("add_invoice", "generate_invoice"):
            if not actor_allowed(actor, action):
                return a._actor_refused(actor, action)
            return a.add_lab_invoice(args) if action == "add_invoice" else a.generate_lab_invoice(args)
        if action in ("set_tier", "set_llm", "advance_clock", "reset", "run_scheduler"):
            if not actor_allowed(actor, action):
                return a._actor_refused(actor, action)
            if action == "set_llm":
                return self._set_llm(args.get("on") is True)
            if action == "run_scheduler":
                new = a.scheduler_tick()
                return AgentResponse(f"Deadline check run: {plural(len(new), 'new reminder')}.", action,
                                     data={"new": [r["id"] for r in new]})
            if action == "reset":
                self.impact = new_impact()          # only the operator's Reset clears the counters
                return self.reset()
            if action == "advance_clock":
                try:
                    hours = max(0.0, min(float(args.get("hours", 0)), 24 * 30))
                except (TypeError, ValueError):
                    return a._blocked_action(action, "INVALID_CHOICE", f"'{args.get('hours')}' is not a number of hours.")
                a.clock.advance(hours=hours)
                self.audit.append("clock_advanced", {"hours": hours, "now": a.clock.now().isoformat()})
                new = a.scheduler_tick()                       # the scheduled deadline check runs when time moves
                extra = f" Deadline check: {plural(len(new), 'new reminder')}." if new else ""
                return AgentResponse(f"Sandbox clock moved forward {hours:g} h to "
                                     f"{a.clock.now().isoformat(timespec='minutes')}." + extra, action)
            name = str(args.get("tier", "ADVISE"))
            if name not in Tier.__members__:
                return a._blocked_action(action, "INVALID_CHOICE", f"'{name}' is not a permission tier.")
            tier = Tier[name]
            if tier >= Tier.ADMIN:
                return a._blocked_action(action, "TIER_TOO_LOW", "ADMIN is never reachable through the assistant.")
            a.session.granted_tier = tier
            self.audit.append("tier_changed", {"tier": tier.name, "by": "operator (screen)"})
            return AgentResponse(f"Permission tier set to {tier.name}.", action)
        return a._blocked_action(action, "NOT_FOUND", f"Unknown action '{action}'.")

    def _check_random_bills(self, n, seed0) -> AgentResponse:
        """Random bills in a throwaway sandbox (its own audit file, deleted afterwards), so the live sandbox, its
        history and its counters stay as they are."""
        import tempfile
        from . import invoicelab
        n = n if isinstance(n, int) and not isinstance(n, bool) else 100
        n = max(1, min(n, 200))
        seed0 = seed0 if isinstance(seed0, int) and not isinstance(seed0, bool) else 0
        tmp = Path(tempfile.mkdtemp())
        try:
            sb = Sandbox(self.profile_path, AuditLog(tmp / "audit.jsonl"), tier=Tier.TRANSACT,
                         start=self.agent.clock.now().replace(tzinfo=None), narrate=False)
            results = []
            for seed in range(seed0, seed0 + n):
                sb.reset()
                results.append(invoicelab.run_check(sb, seed))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        by = {}
        for r in results:
            row = by.setdefault(r["scenario"], {"title": r["title"], "bills": 0, "as_expected": 0})
            row["bills"] += 1
            row["as_expected"] += r["ok"]
        good = sum(r["ok"] for r in results)
        data = {"count": len(results), "as_expected": good, "by_scenario": by, "seed": seed0,
                "examples": results[:6], "wrong": [r for r in results if not r["ok"]][:10]}
        self.audit.append("random_bills_checked", {"count": len(results), "as_expected": good, "seed": seed0})
        return AgentResponse(f"{good} of {len(results)} random bills got the answer the plan requires.",
                             "check_random_bills", data=data)

    def _set_llm(self, on: bool) -> AgentResponse:
        """Operator switch between Qwen and rules-only mode. Fails closed if the model is not reachable."""
        a = self.agent
        if on:
            client = self.llm_client
            if client is None or not getattr(client, "available", lambda: True)():
                why = getattr(client, "reason", "") or "is Ollama running with qwen2.5:7b?"
                return a._blocked_action("set_llm", "LLM_UNAVAILABLE", f"No usable Qwen model ({why}).")
            self.llm = client
        else:
            self.llm = None
        a.llm = self.llm
        model = getattr(self.llm, "model", None)
        self.audit.append("llm_switched", {"on": on, "model": model, "by": "operator (screen)"})
        return AgentResponse(f"Qwen switched {'on (' + model + ')' if on else 'off: rules-only mode'}.", "set_llm",
                             code="SETTING_CHANGED")

    # ------------------------------------------------------------ story autopilot
    def story_step(self, story_id: str, index: int) -> dict:
        story = STORY_BY_ID[story_id]
        if index == 0:
            self.reset(story.setup)
            self.story_ctx = {}
            self.audit.append("story_started", {"story": story.id, "title": story.title})
        step = story.steps[index]
        args = {k: self._resolve(v) for k, v in step["args"].items()}
        resp = self.act(step["actor"], step["action"], args)
        if resp.request_id:
            self.story_ctx["request"] = resp.request_id
        if resp.pending_action:
            self.story_ctx["pending"] = resp.pending_action["id"]
        if resp.code == "EXECUTED":
            self.story_ctx["used"] = args.get("id")
        ok = step["expect"] is None or resp.code == step["expect"]
        return {"story": story.id, "index": index, "of": len(story.steps), "done": index + 1 >= len(story.steps),
                "actor": step["actor"], "action": step["action"], "args": args, "caption": step["caption"],
                "expect": step["expect"], "ok": ok, "response": resp.to_dict()}

    def _resolve(self, v):
        if isinstance(v, str) and v.startswith("$"):
            return self.story_ctx.get(v[1:], v)
        return v

    def run_story(self, story_id: str) -> list:
        return [self.story_step(story_id, i) for i in range(len(STORY_BY_ID[story_id].steps))]

    @staticmethod
    def stories() -> list:
        from .stories import GROUPS
        return [{"id": s.id, "group": s.group, "group_name": GROUPS[s.group], "title": s.title, "shows": s.shows,
                 "steps": [{k: st[k] for k in ("actor", "action", "args", "caption", "expect")} for st in s.steps],
                 "setup": s.setup} for s in STORIES]

    def background_tick(self) -> int:
        """The web server's scheduler thread calls this every few seconds (holding the server lock). Writes only the
        deadline database and the audit log; returns the number of new reminders."""
        return len(self.agent.scheduler_tick())

    def snapshot(self) -> dict:
        return {**self.agent.snapshot(), "llm_switch": self.llm_client is not None,
                "impact": {"scams_stopped": len(self.impact["scams"])},
                "universities": [{"id": k, "name": u["name"], "domain": u["domain"]} for k, u in official.UNIVERSITIES.items()]}
