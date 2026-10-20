"""Scripted sandbox run that produces the execution-evidence bundle.

It plays the 31 stories of plan v4 (studybridge/stories.py) through the same
Sandbox.act() entry point the web UI uses. Output folder evidence/run_<timestamp>/:
  transcript.md            every step: actor, request, outcome code, answer, guard cuts
  audit.jsonl              the hash-chained, masked audit log of the whole run
  audit_tampered_copy.jsonl one character changed in an 'executed' record
  summary.json             per-story results, counts, balances, verification, tamper test
"""
import json
import os
import shutil
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from . import __version__
from .llm import make_client
from .sandbox import Sandbox
from .security.audit import AuditLog
from .stories import GROUPS, STORIES

ACTOR_LABEL = {"student": "Student", "family": "Family", "operator": "Operator"}


def _request_text(step) -> str:
    a = step["args"]
    if step["action"] == "chat":
        return f"`{a['message']}`"
    if step["action"] == "advance_clock":
        return f"*sandbox clock +{a['hours']} h*"
    return f"`{step['action']}` " + ", ".join(f"{k}={v}" for k, v in a.items())


# Information requests (Topic C features outside the payment stories): fixed request -> expected intent.
INFO_REQUESTS = [
    ("compare the cheapest way to send 50000 BDT to CNY within 1 day", "compare_remittance"),
    ("plan my tuition payment", "tuition_plan"),
    ("how can I build my credit history", "credit_plan"),
    ("show my spending insights", "spending_insights"),
    ("show my wallet balance", "wallet_overview"),
]


# Wording the rules reader does not read as a payment (it answers "help" or a planner instead). They show what Qwen
# can add: with Qwen on, the student may be offered Qwen's reading as a question. No pass/fail is claimed for
# them: the result is recorded as it happened.
WORDING_CHECKS = [
    "please clear my tuition fee INV-0003",
    "I would like to get the semester fee INV-0003 taken care of",
    "can you take care of the canteen thing, 38 yuan",
]


RANDOM_BILLS = 200


def _scams(sandbox) -> int:
    return sandbox.snapshot()["impact"]["scams_stopped"]


def run_demo(args, out_root: Path):
    llm = None
    if args.llm:
        client = make_client(args.llm_url, args.model)
        llm = client if client.available() else None
        if llm is None:
            print(f"[warn] model '{client.model}' ({client.label}) not usable: {client.reason or 'not reachable'}; "
                  "running rules-only.", file=sys.stderr)
    mode = "qwen" if llm else "rules"          # named after what really ran, not after the flag
    run_id = datetime.now().strftime(f"run_%Y%m%d_%H%M%S_{mode}")
    out = out_root / run_id
    n = 2
    while out.exists():                     # never append to an earlier run's audit log
        out = out_root / f"{run_id}_{n}"
        n += 1
    run_id = out.name
    out.mkdir(parents=True)
    audit = AuditLog(out / "audit.jsonl")
    start = datetime.fromisoformat((args.today or "2026-10-13") + "T09:00")
    sandbox = Sandbox(args.profile, audit, llm=llm, start=start)

    md = [f"# StudyBridge sandbox run `{run_id}`", "",
          f"- version {__version__}; sandbox clock starts {start.isoformat(timespec='minutes')} for every story",
          f"- LLM: {llm.label + ' ' + llm.model if llm else 'off (rules-only parser, template explanations)'}",
          "- 31 stories from plan v4; each starts from a fresh copy of `data/sample_profile.json`",
          "- All money movement is simulated; no real account is touched.", ""]
    results, codes = [], Counter()
    guard_cuts = 0
    for story in STORIES:
        before = _scams(sandbox)
        steps = sandbox.run_story(story.id)
        ok = all(s["ok"] for s in steps)
        after = _scams(sandbox)
        results.append({"story": story.id, "title": story.title, "group": GROUPS[story.group],
                        "outcome": steps[-1]["response"]["code"], "expected_outcomes_met": ok,
                        "codes": [s["response"]["code"] for s in steps],
                        "scams_stopped_added": after - before})
        md += [f"## {story.id}. {story.title}", "", f"*{story.shows}*", ""]
        if story.setup:
            md += [f"> Story setup (sandbox only): `{json.dumps(story.setup)}`", ""]
        for s in steps:
            r = s["response"]
            codes[r["code"]] += 1
            guard_cuts += len(r.get("guard_removed") or [])
            mark = "✅" if s["ok"] else f"❌ expected {s['expect']}"
            md += [f"**{ACTOR_LABEL[s['actor']]}** {_request_text(s)} → **{r['code']}** {mark}  ",
                   f"<sub>{s['caption']}" + (f" · parser: {r['parse_source']}" if s["action"] == "chat" else "")
                   + "</sub>", "", "```", r["text"], "```", ""]
            if r.get("guard_removed"):
                md += ["Sentences removed by the grounding guard:", ""] + \
                      [f"- ~~{x}~~" for x in r["guard_removed"]] + [""]
        md += [f"Story result: {'all expected outcomes met' if ok else 'MISMATCH'}", ""]
        print(f"[{story.id}] {'ok  ' if ok else 'FAIL'} {story.title:40s} {' -> '.join(results[-1]['codes'])}")

    md += ["## Information requests", "",
           "*Topic C features outside the payment stories: remittance comparison, tuition planner, credit "
           "readiness, spending insights and the wallet. Each starts from a fresh sandbox.*", ""]
    info = []
    for request, intent in INFO_REQUESTS:
        sandbox.reset()
        r = sandbox.act("student", "chat", {"message": request}).to_dict()
        ok = r["intent"] == intent and not r["blocked"]
        guard_cuts += len(r.get("guard_removed") or [])
        info.append({"request": request, "expected_intent": intent, "intent": r["intent"], "code": r["code"],
                     "as_expected": ok})
        md += [f"**Student** `{request}` → intent **{r['intent']}** {'✅' if ok else '❌ expected ' + intent}  ",
               f"<sub>parser: {r['parse_source']}</sub>", "", "```", r["text"], "```", ""]
        if r.get("guard_removed"):
            md += ["Sentences removed by the grounding guard:", ""] + [f"- ~~{x}~~" for x in r["guard_removed"]] + [""]
        print(f"[info] {'ok  ' if ok else 'FAIL'} {request}")

    md += ["## Wording checks", "",
           "*Messages the rules reader does not read as a payment. Nothing here is a pass/fail test: it records what "
           "the readers did. Rules-only runs answer with whatever the rules reader understood (help text or a plan); "
           "with Qwen on, Qwen's reading may be offered to the student as a question. Nothing is paid here.*", ""]
    wording = []
    for request in WORDING_CHECKS:
        sandbox.reset()
        r = sandbox.act("student", "chat", {"message": request}).to_dict()
        role = (sandbox.agent.cases[r["case_id"]]["glass"]["parse"]["role"]["reading"]) if r.get("case_id") else None
        wording.append({"request": request, "code": r["code"], "intent": r["intent"], "reading": role,
                        "offered_qwen_reading": bool(r.get("reading"))})
        md += [f"**Student** `{request}` → **{r['code']}** (reading: {role})  ", "", "```", r["text"], "```", ""]
        print(f"[wording] {r['code']:10s} reading={role}  {request}")

    scams_total = _scams(sandbox)           # the scam counter covers the stories only, not the random bills below
    md += ["## Random bills", "",
           f"*{RANDOM_BILLS} bills made at random by the Invoice lab (seeds 0 to {RANDOM_BILLS - 1}). Each one is a genuine "
           "bill changed in one known way; the answer it must get comes from the plan's rules, not from Gate 1. "
           "Every bill is then sent through the same chat path as a student's request.*", ""]
    from .invoicelab import run_check
    random_bills, by_scenario = [], {}
    for seed in range(RANDOM_BILLS):
        sandbox.reset()
        res = run_check(sandbox, seed)
        random_bills.append({"seed": seed, "scenario": res["scenario"], "expected": res["expected"],
                             "code": res["code"], "as_expected": res["ok"]})
        row = by_scenario.setdefault(res["scenario"], [0, 0])
        row[0] += 1
        row[1] += res["ok"]
    good = sum(b["as_expected"] for b in random_bills)
    md += ["| Scenario | Bills | As expected |", "|---|---|---|"] + \
          [f"| {k} | {v[0]} | {v[1]} |" for k, v in sorted(by_scenario.items())] + \
          ["", f"Total: {good}/{len(random_bills)} as expected; no payment was executed in this section.", ""]
    print(f"[random bills] {good}/{len(random_bills)} as expected")

    md += ["## Safeguards", "",
           "*The attacks from the \"Try to scam StudyBridge\" panel, the scam-message checker on the quiz messages, the "
           "family safe word and the wait for a new payee. Each starts from a fresh sandbox. Nothing is paid.*", ""]
    from .challenge import ATTACKS
    from . import scamcheck
    from .cases import QUIZ
    waiting = {"AWAITING_FAMILY", "ALLOWANCE_REQUESTED"}
    attack_rows = []
    for a in ATTACKS:
        sandbox.reset()
        for _ in range(a.get("burst", 1)):
            r = sandbox.act("student", "chat", {"message": a["message"]})
        kind = "stopped" if r.blocked or r.code == "CLARIFY" else "waits" if r.code in waiting else "answered"
        moved = len(sandbox.agent.wallet._processed)
        attack_rows.append({"id": a["id"], "group": a["group"], "owasp": a["owasp"], "expect": a["expect"],
                            "outcome": kind, "code": r.code, "threat": (r.threat or {}).get("label"),
                            "money_moved": moved, "as_expected": kind == a["expect"] and moved == 0})
    good_attacks = sum(x["as_expected"] for x in attack_rows)
    md += ["| Attack | Group | Expected | Got | Code | Money moved |", "|---|---|---|---|---|---|"] + \
          [f"| {x['id']} | {x['group']} | {x['expect']} | {x['outcome']} | {x['code']} | {x['money_moved']} |"
           for x in attack_rows] + ["", f"Attacks ending as expected with no money moved: {good_attacks}/{len(attack_rows)}.", ""]
    checker = []
    for q in QUIZ:
        res = scamcheck.check(q["text"])
        checker.append({"id": q["id"], "is_scam": q["scam"], "level": res["level"], "signals": [s["kind"] for s in res["signals"]],
                        "as_expected": (res["level"] != "ok") == q["scam"]})
    good_checker = sum(c["as_expected"] for c in checker)
    md += [f"Scam-message checker on the {len(checker)} quiz messages: {good_checker}/{len(checker)} judged as labelled "
           "(a scam is never \"ok\"; a genuine message has no warning).", ""]

    def seq(label, steps):
        out_codes = [c for c in steps]
        md.append(f"- {label}: {' -> '.join(out_codes)}")
        return out_codes

    sandbox.reset()
    sandbox.act("family", "set_safe_word", {"word": "Quokka Parade"})
    rid = sandbox.act("student", "chat", {"message": "pay invoice INV-0003"}).request_id
    word_codes = []
    for w in (None, "wrong one", "wrong two", "wrong three", "quokka parade"):
        word_codes.append(sandbox.act("family", "decide", {"request_id": rid, "approve": True, "safe_word": w}).code)
    sandbox.act("operator", "advance_clock", {"hours": 0.3})
    word_codes.append(sandbox.act("family", "decide", {"request_id": rid, "approve": True, "safe_word": "quokka parade"}).code)
    word_expected = ["SAFE_WORD_REQUIRED", "SAFE_WORD_WRONG", "SAFE_WORD_WRONG", "SAFE_WORD_LOCKED", "SAFE_WORD_LOCKED",
                     "TUITION_APPROVED"]
    seq("Safe word on a CNY 22,800 tuition approval (no word, three wrong tries, the right word while locked, then "
        "after 18 minutes)", word_codes)
    sandbox.reset()
    pid = sandbox.act("family", "add_payee", {"name": "Green Flat Landlord", "type": "landlord",
                                              "account": "6217000099887766", "confirmed": True}).data["payee_id"]
    inv = sandbox.act("operator", "add_invoice", {"payee_id": pid, "kind": "bill", "amount": "250",
                                                  "account_mode": "saved"}).data["invoice_id"]
    cool_codes = [sandbox.act("student", "chat", {"message": f"pay invoice {inv}"}).code]
    sandbox.act("operator", "advance_clock", {"hours": 47})
    cool_codes.append(sandbox.act("student", "chat", {"message": f"pay invoice {inv}"}).code)
    sandbox.act("operator", "advance_clock", {"hours": 2})
    cool_codes.append(sandbox.act("student", "chat", {"message": f"pay invoice {inv}"}).code)
    cool_ok = cool_codes[:2] == ["PAYEE_COOLING_OFF"] * 2 and cool_codes[2] != "PAYEE_COOLING_OFF"
    seq("A payee saved by the family, paid at once / after 47 h / after 49 h", cool_codes)
    # Tuition Deadline Guardian: the reminder level at five points on the sandbox clock.
    sandbox.reset()
    guard_levels = [sandbox.snapshot()["guardian"]["level"]]
    for hrs in (24 * 19, 24 * 5, 24 * 3, 24 * 11):              # 1 Nov, 6 Nov, 9 Nov, 20 Nov (send-by 9 Nov: bank route)
        sandbox.act("operator", "advance_clock", {"hours": hrs})
        guard_levels.append(sandbox.snapshot()["guardian"]["level"])
    guard_ok = guard_levels == ["ok", "ok", "soon", "now", "overdue"]
    seq("Tuition deadline reminder on 13 Oct / 1 Nov / 6 Nov / 9 Nov / 20 Nov", guard_levels)
    # The scheduler behind it: each level raises one reminder, stored in the deadline database, and a repeat check adds none.
    reminder_levels = sorted(r["level"] for r in sandbox.deadlines.reminders(unacked_only=False))
    sandbox.act("operator", "run_scheduler")
    sched_ok = (reminder_levels == ["now", "overdue", "soon"]
                and len(sandbox.deadlines.reminders(unacked_only=False)) == 3
                and [d["invoice_id"] for d in sandbox.deadlines.deadlines()] == ["INV-0003"])
    seq("Reminders stored by the scheduler (soon / now / overdue, one each, none repeated)", reminder_levels)
    # AI-written advice: Qwen (when on) words it, code fills every number; with Qwen off or rejected, code writes it.
    advice = sandbox.act("student", "guardian_advice").data["advice"]
    advice_ok = advice["source"] in ("qwen", "code") and bool(advice["text"])
    seq("Deadline advice written by", [advice["source"]])
    # Explainable risk review: a second request for the same shop and amount is flagged as a possible duplicate.
    sandbox.reset()
    first = sandbox.act("student", "chat", {"message": "request an allowance for Q-TM-0042"})
    second = sandbox.act("student", "chat", {"message": "request an allowance for Q-TM-0043"})
    reqs = {x["id"]: x for x in sandbox.snapshot()["book"]["requests"]}
    risk_levels = [reqs[first.request_id]["risk"]["level"], reqs[second.request_id]["risk"]["level"]]
    risk_ok = risk_levels == ["low", "high"] and reqs[second.request_id]["risk"]["duplicate_of"] == first.request_id
    seq("Risk review of two allowance requests for the same shop and amount (first / second)", risk_levels)
    # Beneficiary change and approval mismatch: an open allowance request, then the landlord's account changes.
    sandbox.reset()
    open_req = sandbox.act("student", "chat", {"message": "request an allowance for RENT-2026-11"})
    chg = sandbox.act("student", "submit_account_change", {"invoice_id": "RENT-2026-11B"})
    sandbox.act("family", "decide", {"request_id": chg.request_id, "approve": True, "phone_verified": True})
    codes_now = [x["code"] for x in {x["id"]: x for x in sandbox.snapshot()["book"]["requests"]}[open_req.request_id]
                 ["risk"]["reasons"]]
    ben_ok = "BENEFICIARY_CHANGE" in codes_now
    seq("Risk reasons on an open request after the landlord's account change was approved", codes_now)
    sandbox.reset()
    pay_req = sandbox.act("student", "chat", {"message": "pay invoice INV-0003"})
    sandbox.agent.book.invoices["INV-0003"]["amount"] = "25800.00"        # the bill is edited after the request
    mm = {x["id"]: x for x in sandbox.snapshot()["book"]["requests"]}[pay_req.request_id]["risk"]
    mismatch_ok = mm["level"] == "high" and any(x["code"] == "APPROVAL_MISMATCH" for x in mm["reasons"])
    seq("Risk level of a tuition request whose bill amount was changed afterwards", [mm["level"]])
    sandbox.reset()
    # Route recommendation with and without a tight deadline.
    from . import remittance
    loose, tight = remittance.compare(50000, "BDT", "CNY"), remittance.compare(50000, "BDT", "CNY", 1)
    route_ok = (loose["recommended"]["provider_id"] == loose["best"]["provider_id"]
                and tight["recommended"]["provider_id"] == tight["fastest"]["provider_id"])
    seq("Remittance recommendation for BDT 50,000 (no deadline / 1-day deadline)",
        [loose["recommended"]["provider"], tight["recommended"]["provider"]])
    md.append("")
    safeguards = {"attacks": {"count": len(attack_rows), "as_expected": good_attacks, "rows": attack_rows},
                  "scam_checker": {"count": len(checker), "as_expected": good_checker, "rows": checker},
                  "safe_word": {"codes": word_codes, "as_expected": word_codes == word_expected},
                  "new_payee_wait": {"codes": cool_codes, "as_expected": cool_ok},
                  "deadline_guardian": {"levels": guard_levels, "as_expected": guard_ok},
                  "deadline_scheduler": {"reminders": reminder_levels, "as_expected": sched_ok},
                  "deadline_advice": {"source": advice["source"], "cut": advice["cut"], "as_expected": advice_ok},
                  "beneficiary_change": {"reasons": codes_now, "as_expected": ben_ok},
                  "approval_mismatch": {"level": mm["level"], "as_expected": mismatch_ok},
                  "risk_review": {"levels": risk_levels, "duplicate_flagged": risk_ok, "as_expected": risk_ok},
                  "route_recommendation": {"no_deadline": loose["recommended"]["provider"],
                                           "one_day_deadline": tight["recommended"]["provider"], "as_expected": route_ok}}
    print(f"[safeguards] attacks {good_attacks}/{len(attack_rows)}, checker {good_checker}/{len(checker)}, "
          f"safe word {'ok' if safeguards['safe_word']['as_expected'] else 'MISMATCH'}, "
          f"new payee {'ok' if cool_ok else 'MISMATCH'}, guardian {'ok' if guard_ok else 'MISMATCH'}, "
          f"scheduler {'ok' if sched_ok else 'MISMATCH'}, advice {'ok' if advice_ok else 'MISMATCH'}, "
          f"beneficiary {'ok' if ben_ok else 'MISMATCH'}, mismatch {'ok' if mismatch_ok else 'MISMATCH'}, "
          f"risk review {'ok' if risk_ok else 'MISMATCH'}, route {'ok' if route_ok else 'MISMATCH'}")

    verification = audit.verify()
    head = {"records": verification.get("records"), "head_hash": audit._last}
    tampered = out / "audit_tampered_copy.jsonl"
    shutil.copy(out / "audit.jsonl", tampered)
    lines = tampered.read_text(encoding="utf-8").splitlines()
    idx = next(i for i, l in enumerate(lines) if '"event":"executed"' in l)
    lines[idx] = lines[idx].replace("SANDBOX_SETTLED", "SANDBOX_SETTLEDX", 1)
    tampered.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tamper_result = AuditLog(tampered).verify()

    passed = sum(r["expected_outcomes_met"] for r in results)
    summary = {"run_id": run_id, "version": __version__, "clock_start": start.isoformat(),
               "llm": llm.model if llm else None, "llm_provider": llm.label if llm else None, "stories": len(results), "stories_as_expected": passed,
               "outcome_codes": dict(sorted(codes.items())), "executed": codes["EXECUTED"],
               "guard_sentences_cut": guard_cuts, "results": results,
               "info_requests": info, "info_requests_as_expected": sum(i["as_expected"] for i in info),
               "scams_stopped": scams_total,
               "random_bills": {"count": len(random_bills), "as_expected": good,
                                "by_scenario": {k: {"bills": v[0], "as_expected": v[1]} for k, v in sorted(by_scenario.items())},
                                "bills": random_bills},
               "safeguards": safeguards, "wording_checks": wording, "readers_per_message": dict(sorted(sandbox.qwen_roles.items())),
               "audit_head": head,
               "audit_verification": verification, "tamper_test_on_copy": tamper_result,
               "python": sys.version.split()[0]}
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    md += ["## Result", "", f"- Stories with all expected outcomes: {passed}/{len(results)}",
           f"- Information requests answered as expected: {sum(i['as_expected'] for i in info)}/{len(info)}",
           f"- Audit head (to detect a truncated log later): {head['records']} records, hash {head['head_hash']}",
           f"- Random bills answered as the plan's rules require: {good}/{len(random_bills)}",
           f"- Safeguards: attacks as expected with no money moved {good_attacks}/{len(attack_rows)}; scam checker "
           f"{good_checker}/{len(checker)}; safe word flow {'as expected' if safeguards['safe_word']['as_expected'] else 'MISMATCH'}; "
           f"new-payee wait {'as expected' if cool_ok else 'MISMATCH'}; deadline reminders {'as expected' if guard_ok else 'MISMATCH'}; "
           f"duplicate flag {'as expected' if risk_ok else 'MISMATCH'}; route recommendation {'as expected' if route_ok else 'MISMATCH'}",
           f"- Executed payments: {codes['EXECUTED']}; sentences cut by the guard: {guard_cuts}",
           f"- Scams stopped across all stories (each counted once): {scams_total}. "
           "Each story's share is in summary.json (`scams_stopped_added`).",
           f"- Audit chain verification: {verification}",
           f"- Tamper test (one character changed in a copy): {tamper_result}", ""]
    (out / "transcript.md").write_text("\n".join(md), encoding="utf-8")
    print(f"\n{passed}/{len(results)} stories as expected. Evidence written to {out}")
    print(json.dumps({"audit": verification, "tamper_test": tamper_result}, default=str))
    return out
