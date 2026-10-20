"""Permission tiers and the policy engine.

The LLM never calls a tool directly. It can only propose an intent; this
engine decides whether the session's granted tier allows it, whether the
user must confirm it, and whether it stays inside the money limits.
"""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import IntEnum

from ..config import LIMITS


class Tier(IntEnum):
    PUBLIC = 0     # rates and general guidance, no personal data
    READ = 1       # read own wallet, transactions
    ADVISE = 2     # personalised plans; still no money movement
    TRANSACT = 3   # sandbox money movement, always with user confirmation
    ADMIN = 4      # configuration; never reachable through the agent


TOOL_TIERS = {
    "help": Tier.PUBLIC,
    "fx_quote": Tier.PUBLIC,
    "wallet_overview": Tier.READ,
    "spending_insights": Tier.READ,
    "compare_remittance": Tier.ADVISE,
    "tuition_plan": Tier.ADVISE,
    "credit_plan": Tier.ADVISE,
    "payment_status": Tier.READ,
    "convert_currency": Tier.TRANSACT,
    "pay": Tier.TRANSACT,
    "request_allowance": Tier.TRANSACT,
}
# Intents that move money or start a money approval: both parsers must agree.
MONEY_MOVING = {"convert_currency", "pay", "request_allowance"}

# Who is acting is a separate idea from the tier. It is set only by the screen
# or the command line (never by the model or by message text).
ACTOR_ACTIONS = {
    "chat": {"student"},
    "confirm": {"student"},
    "cancel": {"student"},
    "acknowledge": {"student"},            # opens the family's approval; starts the 2-minute confirmation
    "request_limit_raise": {"student"},
    "submit_account_change": {"student"},
    "decide": {"family"},
    "set_limit": {"family"},
    "set_doc": {"family"},
    "set_safe_word": {"family"},             # the family's own safe word (never chat)
    "add_payee": {"family"},                 # only the family saves a payee; it then waits 48 hours
    "cancel_allowance": {"family"},          # the student has no cancel button (plan §5.2)
    "ask_cancel": {"student"},               # ...but can ask the family to cancel
    "check_message": {"student"},
    "verify_bill": {"student", "family"},     # compare a bill with the university's official website (reads only)            # paste a message: is it a scam? (text only, cannot start a payment)
    "scam_quiz": {"student"},                # Spot-the-scam quiz
    "guardian_advice": {"student"},          # advice for the next tuition deadline (read-only; Qwen may word it)
    "ack_reminder": {"student"},             # mark a deadline reminder as seen (pays nothing)
    "ack_alert": {"family"},                 # the family marks a stopped payment as seen
    "add_bill": {"student"},                 # a bill typed in from paper; Gate 1 still judges it
    "add_message_bill": {"student"},
    "report_message": {"student"},           # report a message as a scam: its bill is locked; the family sees it         # file the bill attached to a message from an unknown sender
    "set_pin": {"family"},                   # the family PIN that locks the Family screen
    "unlock": {"family"},
    "lock": {"family"},
    "pot_add": {"family"},                   # the family puts money aside in the tuition reserve (only tuition can use it)
    "pot_release": {"family"},               # ...and takes it out again; the student only sees it
    "set_bank_limit": {"bank"},              # the simulated bank's daily card limit, on the bank's screen only
    # Sandbox operator controls (the person running the demo, from the screen).
    "set_tier": {"operator"},
    "set_llm": {"operator"},
    "advance_clock": {"operator"},
    "run_scheduler": {"operator"},           # run the deadline check now
    "reset": {"operator"},
    "add_invoice": {"operator"},             # Invoice lab: a bill typed in on the screen (never from chat)
    "generate_invoice": {"operator"},        # Invoice lab: a bill made at random by the code
    "check_random_bills": {"operator"},      # Invoice lab: many random bills in a throwaway sandbox
    "send_message": {"operator"},            # a sample message (university, landlord, shop or a scam) arrives
}


def actor_allowed(actor: str, action: str) -> bool:
    return actor in ACTOR_ACTIONS.get(action, set())


@dataclass
class Decision:
    allowed: bool
    needs_confirmation: bool
    reason: str


@dataclass
class Session:
    granted_tier: Tier = Tier.ADVISE
    spent_today_home: Decimal = Decimal(0)
    spent_today_tuition: Decimal = Decimal(0)       # tuition invoices count against their own cap, not the daily one
    spent_on: date = field(default_factory=date.today)

    def roll_day(self, today: date):
        if today != self.spent_on:
            self.spent_on, self.spent_today_home, self.spent_today_tuition = today, Decimal(0), Decimal(0)


class PolicyEngine:
    def __init__(self, limits: dict = None):
        self.limits = limits or LIMITS

    def check_tool(self, tool: str, session: Session) -> Decision:
        required = TOOL_TIERS.get(tool)
        if required is None:
            return Decision(False, False, f"tool '{tool}' is not on the allowlist")
        if required >= Tier.ADMIN:
            return Decision(False, False, "admin tools are not reachable through the agent")
        if session.granted_tier < required:
            return Decision(False, False,
                            f"'{tool}' needs tier {required.name}; this session has {session.granted_tier.name}")
        return Decision(True, tool in MONEY_MOVING, "ok")

    def check_amount(self, amount_home: Decimal, session: Session, today: date, tuition: bool = False) -> Decision:
        session.roll_day(today)
        if amount_home <= 0:
            return Decision(False, False, "amount must be positive")
        if tuition:
            cap = self.limits["tuition_per_tx_home"]
            if session.spent_today_tuition + amount_home > cap:
                return Decision(False, False, f"amount exceeds the tuition limit of BDT {cap:,} a day")
            return Decision(True, True, "ok")
        if amount_home > self.limits["per_tx_home"]:
            return Decision(False, False,
                            f"amount exceeds the per-transaction limit of BDT {self.limits['per_tx_home']:,}")
        if session.spent_today_home + amount_home > self.limits["daily_home"]:
            return Decision(False, False,
                            f"amount would exceed the daily limit of BDT {self.limits['daily_home']:,}")
        return Decision(True, True, "ok")
