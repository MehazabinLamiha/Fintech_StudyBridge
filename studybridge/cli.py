"""Command-line entry points: chat, demo, web, verify-audit, stories, refresh-official."""
import argparse
import os
import sys
from datetime import date, datetime
from pathlib import Path

from . import DEFAULT_PROFILE, PROJECT_ROOT
from .agent import StudentFinanceAgent
from .llm import make_client
from .security.audit import AuditLog
from .security.permissions import Tier
from .wallet import SandboxWallet


def build_agent(args) -> StudentFinanceAgent:
    llm = None
    if args.llm:
        client = make_client(args.llm_url, args.model)
        if client.available():
            llm = client
        else:
            print(f"[warn] model '{client.model}' ({client.label}) not usable: {client.reason or 'not reachable'}; "
                  "running rules-only.", file=sys.stderr)
    today = date.fromisoformat(args.today) if args.today else None
    return StudentFinanceAgent(SandboxWallet.from_file(args.profile), AuditLog(args.audit),
                               granted_tier=Tier[args.tier], llm=llm, today=today)


def cmd_chat(args):
    agent = build_agent(args)
    print("StudyBridge sandbox (you are the student). Commands: /confirm <id>, /cancel <id>, /wallet, "
          "/verify, /quit\nFamily actions (sandbox only, from this screen): /approve <REQ-id>, /reject <REQ-id>")
    while True:
        try:
            msg = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not msg:
            continue
        if msg in ("/quit", "/exit"):
            break
        if msg.startswith("/confirm "):
            resp = agent.confirm(msg.split(maxsplit=1)[1])
        elif msg.startswith("/cancel "):
            resp = agent.cancel(msg.split(maxsplit=1)[1])
        elif msg.startswith(("/approve ", "/reject ")):
            # The actor comes from the command, not from chat text.
            resp = agent.family_decide(msg.split(maxsplit=1)[1], msg.startswith("/approve"), actor="family")
        elif msg == "/wallet":
            resp = agent.handle("show my wallet balance")
        elif msg == "/verify":
            print(agent.audit.verify())
            continue
        else:
            resp = agent.handle(msg)
        print(f"\nstudybridge> {resp.text}")


def cmd_verify(args):
    result = AuditLog(args.audit).verify()
    print(result)
    sys.exit(0 if result["ok"] else (2 if result.get("error") else 1))   # 2 = no log found, 1 = chain broken


def main(argv=None):
    ap = argparse.ArgumentParser(prog="studybridge")
    ap.add_argument("--profile", default=str(DEFAULT_PROFILE))
    ap.add_argument("--audit", default=str(PROJECT_ROOT / "var" / "audit.jsonl"))
    ap.add_argument("--tier", default=None, choices=[t.name for t in Tier if t < Tier.ADMIN],
                    help="what the assistant may do (default: TRANSACT for the web app, where the student still "
                         "confirms every payment; ADVISE elsewhere)")
    ap.add_argument("--llm", action="store_true", default=os.environ.get("STUDYBRIDGE_LLM") == "1",
                    help="use a model for parsing and explanations: local Ollama, or a hosted OpenAI-style API "
                         "when --llm-url or GROQ_API_KEY / STUDYBRIDGE_LLM_KEY is set")
    ap.add_argument("--model", default=None, help="model name (default qwen2.5:7b on Ollama, the Groq Qwen when hosted)")
    ap.add_argument("--llm-url", default=None, help="base URL of an OpenAI-style API, e.g. https://api.groq.com/openai/v1")
    ap.add_argument("--today", default=os.environ.get("STUDYBRIDGE_TODAY") or None,
                    help="override today's date (YYYY-MM-DD) for reproducible runs (or set STUDYBRIDGE_TODAY)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("chat")
    sub.add_parser("verify-audit")
    sub.add_parser("stories", help="list the 31 test stories")
    sub.add_parser("refresh-official", help="fetch each university's official payment page into data/official_pages")
    demo = sub.add_parser("demo")
    demo.add_argument("--out", default=str(PROJECT_ROOT / "evidence"))
    web = sub.add_parser("web")
    web.add_argument("--state", default=os.environ.get("STUDYBRIDGE_STATE"),
                     help="save and restore approvals, balances and totals in this JSON file (optional)")
    web.add_argument("--db", default=os.environ.get("STUDYBRIDGE_DB"),
                     help="SQLite file for deadlines and reminders (default: next to --state, else in memory)")
    web.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8765)))
    web.add_argument("--host", default="127.0.0.1", help="keep 127.0.0.1 unless inside a container")
    args = ap.parse_args(argv)
    args.tier = args.tier or ("TRANSACT" if args.cmd == "web" else "ADVISE")

    if args.cmd == "chat":
        cmd_chat(args)
    elif args.cmd == "verify-audit":
        cmd_verify(args)
    elif args.cmd == "demo":
        from .demo import run_demo
        run_demo(args, Path(args.out))
    elif args.cmd == "refresh-official":
        from . import official
        for uni_id, uni in official.UNIVERSITIES.items():
            for i, url in enumerate(uni["pages"]):
                try:
                    rec = official.save_copy(official.SAVED, uni_id, i, url, official.fetch(url, uni), datetime.now())
                    print(f"saved  {uni_id}-{i + 1}  {url}  ({len(rec['text'])} chars)")
                except (OSError, ValueError) as exc:
                    print(f"FAILED {uni_id}-{i + 1}  {url}  {type(exc).__name__}: {exc}")
    elif args.cmd == "stories":
        from .stories import GROUPS, STORIES
        for s in STORIES:
            print(f"{s.id}  {GROUPS[s.group]:24s} {s.title}")
    elif args.cmd == "web":
        from .sandbox import Sandbox
        from .web import serve
        probe = build_agent(args)
        start = datetime.fromisoformat(args.today + "T09:00") if args.today else None
        # The Qwen switch on the screen turns this client on; it is only used if the model answers then.
        client = probe.llm or make_client(args.llm_url, args.model)
        sandbox = Sandbox(args.profile, probe.audit, llm=probe.llm, tier=Tier[args.tier], start=start,
                          ticking=True, llm_client=client, state_path=args.state,
                          official_online=os.environ.get("STUDYBRIDGE_OFFLINE") != "1",
                          db_path=args.db or (str(Path(args.state).with_suffix('.db')) if args.state else None))
        serve(sandbox, args.port, args.host)
