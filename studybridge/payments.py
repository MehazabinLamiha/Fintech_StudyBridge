"""Payment rules (plan v3): payee types, invoices, Gate 1, the everyday path,
allowances (single-use and monthly rent), one-day limit raises, new-account
checks with a 24-hour hold, family approvals and the simulated bank review.

Nothing in this module talks to the language model. Payee, amount, account
and payee type come from stored data. The message can only select a stored
invoice or a saved payee, plus an amount for food and QR payments (which
have no invoice and are therefore capped).
"""
import hashlib
import hmac
import re
import secrets
import unicodedata
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import NoReturn

from .config import EXEMPT_TYPES, PAYEE_TYPES, PAYMENT
from .money import D, convert_mid, q, to_usd
from .reasons import PaymentBlocked
from .security.audit import mask_account
from . import xray

DOC_ID = re.compile(r"\b(?:INV|RENT|Q|LAB|BILL)-[A-Z0-9]+(?:-[A-Z0-9]+)*\b", re.IGNORECASE)


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts).isoformat(timespec="minutes")


class PaymentBook:
    """Stored payment data plus the approval state of the sandbox session."""

    def __init__(self, profile: dict, clock, payees: dict = None):
        self.clock = clock
        # Pass the wallet's payee records so an approved account change is the account that gets paid.
        self.payees = payees if payees is not None else {p["id"]: dict(p) for p in profile.get("payees", [])}
        self.invoices = {i["id"].upper(): dict(i) for i in profile.get("invoices", [])}
        self.documents = {k: dict(v) for k, v in profile.get("documents", {}).items()}
        self.owner = dict(profile.get("owner", {}))
        fam = profile.get("family", {})
        self.family_name = fam.get("name", "Family")
        self.family_limit = D(fam.get("daily_limit_cny", PAYMENT["family_limit_default_cny"]))
        self.bank_limit_usd = PAYMENT["bank_daily_limit_usd"]   # set on the bank's screen only
        self.messages = []      # bills sent to the student by message (see inbox.py)
        for inv in sorted(self.invoices.values(), key=lambda i: i.get("issued", "")):
            if inv.get("arrives_as"):   # a sample bill that reaches the student only as a message (the scams)
                m = inv["arrives_as"]
                self.messages.append({
                    "id": f"MSG-{len(self.messages) + 1}", "template": None, "from": m["from"], "official": False,
                    "subject": m["subject"], "text": m["text"], "received": inv.get("issued", "") + "T09:00",
                    "bill": {"kind": inv.get("kind"), "amount": str(q(inv["amount"])), "currency": inv["currency"],
                             "purpose": inv["purpose"], "payee": inv.get("issuer") or self.payees[inv["payee_id"]]["name"]},
                    "invoice_id": inv["id"], "attached": True})
        self._message_specs = {}  # message id -> the attached bill, account included (kept out of snapshots)
        self.bank_log = []        # every simulated bank review, approved or rejected (the bank's screen)
        self.requests = {}      # family approval requests: tuition, allowance, limit_raise, account_change
        self.allowances = {}
        self.limit_raises = {}  # date -> CNY limit for that one day, approved by the family
        self._new_accounts = {}  # request id -> reported account number (kept out of snapshots)
        self._spent = defaultdict(Decimal)   # (date, bucket) -> CNY; in memory only (known weakness)
        self.safe_word = None                # {"salt", "hash", "set_at"}: only a salted hash is kept, never the word
        self.safe_word_fails = []            # sandbox times of wrong tries
        self.safe_word_locked_until = None

    # ------------------------------------------------------------ counters
    def spent_today(self, bucket: str) -> Decimal:
        return self._spent[(self.clock.today(), bucket)]

    def family_limit_today(self) -> Decimal:
        return max(self.family_limit, self.limit_raises.get(self.clock.today(), Decimal(0)))

    def family_remaining(self) -> Decimal:
        return max(Decimal(0), self.family_limit_today() - self.spent_today("family"))

    def record_payment(self, payee_id: str, amount: Decimal, counts_family: bool, card: bool):
        d = self.clock.today()
        self._spent[(d, "payee:" + payee_id)] += amount
        if counts_family:
            self._spent[(d, "family")] += amount
        if card:
            self._spent[(d, "card")] += amount

    def bank_limit_cny(self) -> Decimal:
        return q(convert_mid(self.bank_limit_usd, "USD", PAYMENT["currency"]))

    def needs_bank_review(self, amount: Decimal) -> bool:
        """True if this card payment would take today's card total past the daily bank limit."""
        return self.spent_today("card") + amount > self.bank_limit_cny()

    def bank_check(self, amount: Decimal, allowance: dict = None):
        """Simulated daily bank limit (team design). Only this payment is blocked, and only when no
        simulated bank review already covers it."""
        if self.review_covers(allowance):
            return
        used, limit = self.spent_today("card"), self.bank_limit_cny()
        if used + amount > limit:
            lapsed = bool(allowance and allowance.get("bank_review"))
            raise PaymentBlocked("BANK_DAILY_LIMIT_REACHED",
                                 f"Card spending today is CNY {used:,.2f}; adding CNY {amount:,.2f} passes the "
                                 f"CNY {limit:,.2f} (USD {self.bank_limit_usd:,.0f}) daily bank limit, "
                                 + ("and the bank review's 72-hour window has passed." if lapsed
                                    else "and no bank review covers this payment."))

    def review_covers(self, allowance: dict = None) -> bool:
        """True while a simulated bank review attached to this allowance is inside its 72-hour window."""
        br = (allowance or {}).get("bank_review")
        return bool(br) and br.get("decision") == "approved" and self.clock.ts() <= br.get("window_until_ts", 0)

    @staticmethod
    def bill_month(pay: dict) -> str:
        """Calendar month a bill belongs to (from its stored due date)."""
        return (pay.get("due") or "")[:7] or None

    # ------------------------------------------------------------ lookups
    def match_payees(self, text: str) -> list:
        t = (text or "").lower()
        hits = []
        for p in self.payees.values():
            keys = [p["id"].lower(), p["name"].lower()] + [a.lower() for a in p.get("aliases", [])]
            if any(re.search(r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])", t) for k in keys):
                hits.append(p["id"])
        return hits

    def _owner_of(self, account: str):
        return next((p for p in self.payees.values() if p.get("account_number") == account), None)

    @staticmethod
    def reportable_change(inv: dict, payee: dict) -> bool:
        """A different account that the family may check by phone: a landlord's or shop's bill, or a
        university invoice that itself says the bank details changed (stored flag). Anything else with
        a different account (look-alike, agent or personal wallet on a tuition invoice) is simply refused."""
        return payee["type"] in ("landlord", "merchant") or (
            payee["type"] == "institution" and bool(inv.get("claims_new_account")))

    def doc_label(self, key: str) -> str:
        return self.documents.get(key, {}).get("label", key)

    def verified_open_invoices(self, payee_id: str) -> list:
        p = self.payees[payee_id]
        return [i["id"] for i in self.invoices.values()
                if i["payee_id"] == payee_id and i["status"] == "open"
                and i.get("account_number") == p.get("account_number")]

    # ------------------------------------------------------------ Gate 1
    def gate1(self, invoice_id=None, named_payee=None, amount=None, currency=None) -> tuple:
        """Gate 1: invoice, payee and documents.

        Returns (payment, checks). Raises PaymentBlocked carrying the checks
        made so far, so the Glass Box can show exactly which one failed.
        """
        checks = []
        pay = {"invoice_id": None, "payee_id": None, "payee_name": None, "payee_type": None,
               "amount": None, "currency": None, "account": None, "purpose": None, "kind": None,
               "memo": "", "due": None}

        def ok(name, detail=""):
            checks.append({"check": name, "ok": True, "detail": detail})

        def fail(code, name, detail) -> NoReturn:
            checks.append({"check": name, "ok": False, "code": code, "detail": detail})
            err = PaymentBlocked(code, detail)
            err.checks, err.payment = checks, pay
            raise err

        self.expire()
        inv = None
        if invoice_id:
            inv = self.invoices.get(invoice_id.upper())
            if inv is None:
                fail("INVOICE_NOT_FOUND", "Invoice exists", f"There is no stored invoice {invoice_id.upper()}.")
            ok("Invoice exists", f"{inv['id']}: {inv['purpose']}")
            if named_payee and named_payee != inv["payee_id"]:
                fail("PAYEE_NOT_MATCHING_INVOICE", "Payee matches invoice",
                     f"The request names {self.payees[named_payee]['name']}, but {inv['id']} is from "
                     f"{self.payees[inv['payee_id']]['name']}.")
            payee_id = inv["payee_id"]
        else:
            payee_id = named_payee

        payee = self.payees.get(payee_id) if payee_id else None
        if payee is None:
            fail("PAYEE_NOT_VERIFIED", "Saved payee",
                 "Payments only go to payees the family has saved. Only the family can save one.")
        pay.update(payee_id=payee["id"], payee_name=payee["name"], payee_type=payee["type"],
                   currency=payee["currency"])

        if PAYEE_TYPES[payee["type"]] and inv is None:
            options = self.verified_open_invoices(payee["id"])
            fail("INVOICE_REQUIRED", "Invoice present",
                 f"{payee['name']} has payee type '{payee['type']}' (from stored data, not from the message), "
                 f"so a stored invoice, bill or quote is required."
                 + (f" Open documents from this payee: {', '.join(options)}." if options else ""))
        ok("Payee type", f"{payee['name']}: {payee['type']} (from stored data, never from the message)")
        wait = self.cooling_left(payee)
        if wait is not None:
            fail("PAYEE_COOLING_OFF", "New payee wait",
                 f"{payee['name']} was saved by the family on {payee['saved_on']}. A new payee can be paid after "
                 f"{_iso(payee['saved_ts'] + PAYMENT['new_payee_hold_hours'] * 3600)} "
                 f"({PAYMENT['new_payee_hold_hours']}-hour wait).")
        if payee.get("saved_ts") is not None and payee["type"] not in EXEMPT_TYPES:
            ok("New payee wait", f"{payee['name']} has been saved for over {PAYMENT['new_payee_hold_hours']} hours")

        if inv is not None:
            pay.update(invoice_id=inv["id"], purpose=inv["purpose"], kind=inv.get("kind"),
                       memo=inv.get("memo", ""), account=inv.get("account_number"), due=inv.get("due"))
            if inv["status"] == "paid":
                fail("INVOICE_ALREADY_PAID", "Invoice still open", f"{inv['id']} was already paid.")
            if inv.get("reported"):
                fail("REPORTED_AS_SCAM", "Not reported as a scam",
                     f"{inv['id']} came in a message the student reported as a scam on {inv['reported']}.")
            if inv.get("valid_until") and date.fromisoformat(inv["valid_until"]) < self.clock.today():
                fail("QUOTE_EXPIRED", "Invoice still open", f"{inv['id']} was valid until {inv['valid_until']}.")
            ok("Invoice still open", f"due {inv.get('due', '—')}" if inv.get("due")
               else f"valid until {inv.get('valid_until', '—')}")

            amt, ccy = q(inv["amount"]), inv["currency"]
            if amount is not None and (q(amount) != amt or (currency and currency != ccy)):
                fail("AMOUNT_NOT_MATCHING_INVOICE", "Amount matches invoice",
                     f"The request says {currency or ccy} {q(amount):,.2f}; {inv['id']} is stored as {ccy} {amt:,.2f}.")
            pay.update(amount=amt, currency=ccy)
            ok("Amount matches invoice", f"{ccy} {amt:,.2f} (amount taken from the invoice)")

            acct = inv.get("account_number")
            if acct and acct == payee.get("pending_account"):
                fail("ACCOUNT_ON_HOLD", "Verified account",
                     f"The family checked {mask_account(acct)} by phone. It can be paid after "
                     f"{_iso(payee['hold_until_ts'])} (24-hour wait).")
            if acct != payee.get("account_number") or not payee.get("verified"):
                owner = self._owner_of(acct)
                who = (f"it belongs to {owner['name']} ({owner['type']})" if owner and owner is not payee
                       else "it is not on file")
                code = "ACCOUNT_CHANGED" if self.reportable_change(inv, payee) else "PAYEE_NOT_VERIFIED"
                fail(code, "Verified account",
                     f"{inv['id']} asks for payment to account {mask_account(acct)}; {who}. "
                     f"{payee['name']}'s verified account is {mask_account(payee.get('account_number', ''))}.")
            if inv.get("kind") == "tuition" and payee["type"] != "institution":
                fail("PAYEE_NOT_VERIFIED", "Verified account",
                     f"Tuition can only go to the university, or to a payment company the university names in the "
                     f"admission letter (Bangladesh Bank FEPD-1 Circular No. 40, para 10). {payee['name']} is a "
                     f"'{payee['type']}' payee, so this tuition bill is blocked.")
            ok("Verified account", f"{mask_account(acct)} matches the saved, verified account")

            missing = [d for d in inv.get("required_docs", []) if not self.documents.get(d, {}).get("ready")]
            if missing:
                fail("DOCS_MISSING", "Documents ready",
                     "Not ready: " + ", ".join(self.doc_label(d) for d in missing) + ".")
            ok("Documents ready", ", ".join(self.doc_label(d) for d in inv.get("required_docs", [])) or "none required")
        else:
            # Food / QR: no invoice exists, so the amount comes from the request and is capped.
            amt = q(amount)
            pay.update(amount=amt, purpose=payee["type"].replace("_", " ") + " payment")
            ok("Name-only check", f"{payee['name']} is a saved '{payee['type']}' payee")
            cap = PAYMENT["exempt_cap_cny"]
            if amt > cap:
                fail("EXEMPT_LIMIT_EXCEEDED", "Exempt cap",
                     f"CNY {amt:,.2f} is above the CNY {cap:,.0f} cap for each {payee['type']} payment.")
            already = self.spent_today("payee:" + payee["id"])
            if already > 0 and already + amt > cap:
                fail("SPLIT_PAYMENT_SUSPECTED", "Exempt cap",
                     f"CNY {already:,.2f} already went to {payee['name']} today; adding CNY {amt:,.2f} passes "
                     f"the CNY {cap:,.0f} cap.")
            ok("Exempt cap", f"CNY {amt:,.2f} ≤ CNY {cap:,.0f}")
        return pay, checks

    # ------------------------------------------------------------ everyday path
    def everyday_route(self, pay: dict) -> dict:
        """Gate 2 (everyday): inside the family daily limit, or covered by an allowance; then the
        simulated daily bank limit."""
        remaining = self.family_remaining()
        amt = pay["amount"]
        if pay["payee_type"] in EXEMPT_TYPES:
            if amt > remaining:
                raise PaymentBlocked("DAILY_LIMIT_REACHED",
                                     f"CNY {amt:,.2f} is more than the CNY {remaining:,.2f} left of today's family "
                                     f"daily limit (CNY {self.family_limit_today():,.0f}).")
            self.bank_check(amt)
            return {"mode": "family_limit", "remaining": remaining}
        if amt <= remaining:
            self.bank_check(amt)
            return {"mode": "family_limit", "remaining": remaining}
        a = self.find_allowance(pay, remaining)
        self.bank_check(amt, a)
        return {"mode": "allowance", "allowance": a}

    def find_allowance(self, pay: dict, remaining: Decimal = None) -> dict:
        self.expire()
        payee_id, amount, month = pay["payee_id"], pay["amount"], self.bill_month(pay)
        name = self.payees[payee_id]["name"]
        monthly = [a for a in self.allowances.values() if a.get("monthly") and a["payee_id"] == payee_id
                   and amount <= a["amount"]]
        if month in self.monthly_months_used(payee_id):
            raise PaymentBlocked("ALLOWANCE_USED", f"A monthly rent allowance for {name} was already used for "
                                                   f"{month}. Rent is paid once per calendar month.")
        same = [a for a in self.allowances.values() if not a.get("monthly") and a["payee_id"] == payee_id
                and amount <= a["amount"]]          # "up to": a lower price at the same shop is fine
        usable = [a for a in monthly + same if a["status"] == "open"]
        if usable:      # prefer one whose bank review still covers the day's card total
            return sorted(usable, key=lambda a: not self.review_covers(a))[0]
        if any(a["status"] == "used" for a in same):
            raise PaymentBlocked("ALLOWANCE_USED", f"The allowance for {name}, CNY {amount:,.2f} was already used once.")
        if any(a["status"] == "expired" for a in same + monthly):
            raise PaymentBlocked("ALLOWANCE_EXPIRED", f"The allowance for {name}, CNY {amount:,.2f} has expired.")
        other = [a for a in self.allowances.values() if a["status"] == "open"
                 and (a["payee_id"] == payee_id or a.get("quoted", a["amount"]) == amount)]
        if other:
            a = other[0]
            raise PaymentBlocked("ALLOWANCE_MISMATCH",
                                 f"Open allowance {a['id']} is for {a['payee_name']}, up to CNY {a['amount']:,.2f}. "
                                 f"This payment is to {name}, CNY {amount:,.2f}.")
        left = remaining if remaining is not None else self.family_remaining()
        raise PaymentBlocked("ALLOWANCE_NEEDED",
                             f"CNY {amount:,.2f} is more than the CNY {left:,.2f} left of today's family daily "
                             f"limit (CNY {self.family_limit_today():,.0f}).")

    # ------------------------------------------------------------ allowance requests
    def bank_review(self, pay: dict) -> dict:
        """Simulated bank review (code only, not a real bank decision)."""
        inv = self.invoices[pay["invoice_id"]]
        today = self.clock.today()
        valid = not inv.get("valid_until") or date.fromisoformat(inv["valid_until"]) >= today
        checks = [
            ("Merchant quote or bill", inv.get("kind") in ("quote", "bill"), f"document kind: {inv.get('kind')}"),
            ("Purpose stated", bool(inv.get("purpose")), inv.get("purpose") or "no purpose on the document"),
            ("Quote still valid", valid, f"valid until {inv.get('valid_until', '—')}" if valid
             else f"the quote expired on {inv['valid_until']}"),
        ]
        usd = q(to_usd(pay["amount"], pay["currency"]))
        card_usd = q(to_usd(self.spent_today("card"), pay["currency"]))
        review = {"needed": True, "amount_usd": usd, "card_today_usd": card_usd,
                  "limit_usd": self.bank_limit_usd,
                  "checks": [{"check": c, "ok": o, "detail": d} for c, o, d in checks]}
        failed = [c for c in review["checks"] if not c["ok"]]
        log = {"invoice_id": inv["id"], "payee_name": self.payees[inv["payee_id"]]["name"], "amount": pay["amount"],
               "amount_usd": usd, "at": _iso(self.clock.ts())}
        if failed:
            review["decision"] = "rejected"
            reason = "; ".join(f"{c['check']}: {c['detail']}" for c in failed)
            self.bank_log.append({**log, "decision": "rejected", "reason": reason})
            err = PaymentBlocked("BANK_REVIEW_REJECTED", reason)
            err.review = review
            raise err
        until = self.clock.ts() + PAYMENT["allowance_default_hours"] * 3600
        review.update(decision="approved", approved_amount=pay["amount"], approved_currency=pay["currency"],
                      window_until=_iso(until), window_until_ts=until)
        self.bank_log.append({**log, "decision": "approved", "window_until": review["window_until"]})
        return review

    def monthly_months_used(self, payee_id: str) -> set:
        """Bill months already paid by any monthly allowance for this payee (one bill per month, per landlord)."""
        return {m for a in self.allowances.values() if a.get("monthly") and a["payee_id"] == payee_id
                for m in a["used_months"]}

    def open_monthly_for(self, payee_id: str):
        self.expire()
        for a in self.allowances.values():
            if a.get("monthly") and a["payee_id"] == payee_id and a["status"] == "open":
                return a
        for r in self.requests.values():
            if r["kind"] == "allowance" and r.get("monthly") and r["payee_id"] == payee_id and r["status"] == "pending":
                return r
        return None

    def open_allowance_count(self) -> int:
        self.expire()
        return (sum(a["status"] == "open" for a in self.allowances.values())
                + sum(r["kind"] == "allowance" and r["status"] == "pending" for r in self.requests.values()))

    def account_change_rejected(self, invoice_id) -> bool:
        """True if the family already rejected a report of a new account for this invoice."""
        inv = (invoice_id or "").upper()
        return any(r["kind"] == "account_change" and r["invoice_id"] == inv and r["status"] == "rejected"
                   for r in self.requests.values())

    def pending_request_for(self, invoice_id: str, kind: str):
        self.expire()
        for r in reversed(list(self.requests.values())):
            if r["invoice_id"] == invoice_id and r["kind"] == kind and r["status"] in ("pending", "approved"):
                return r
        return None

    # ------------------------------------------------------------ explainable risk review (family approval card)
    def risk_review(self, kind: str, pay: dict, warnings=()) -> dict:
        """Why a request might be unsafe, in plain words, for the family's approval card. Written by code only.

        Reasons: another open request for the same payee and amount in the last 24 hours (a possible duplicate),
        every scam warning the app already raised, a large amount, and a payee saved by the family in the last week.
        `duplicate_of` is the earlier request id, if any. Nothing here blocks a payment: the gates do that. A
        duplicate or a warning makes the request carry a warning, which asks for the safe word when one is set.
        """
        now = self.clock.ts()
        reasons, duplicate_of = [], None
        for r in reversed(list(self.requests.values())):
            if r["kind"] != kind or r["status"] not in ("pending", "approved"):
                continue
            if r.get("payee_id") != pay.get("payee_id") or r["currency"] != pay["currency"] or r["amount"] != pay["amount"]:
                continue
            made = r.get("created_ts", r["expires_ts"] - PAYMENT["family_approval_hours"] * 3600)
            if now - made <= PAYMENT["duplicate_window_hours"] * 3600:
                duplicate_of = r["id"]
                reasons.append({"code": "DUPLICATE_REQUEST", "level": "high", "title": "Possible duplicate",
                                "why": f"Same payee and amount as {r['id']} (made {_iso(made)[11:16]}, "
                                       f"{r['status']}). Check this is not the same bill sent twice."})
                break
        for w in warnings:
            reasons.append({"code": "WARNING", "level": "high", "title": "Scam signal", "why": w})
        cny = convert_mid(pay["amount"], pay["currency"], "CNY")
        if cny >= PAYMENT["safe_word_from_cny"]:
            reasons.append({"code": "LARGE_AMOUNT", "level": "medium", "title": "Large amount",
                            "why": f"About CNY {cny:,.0f}. Large payments are the ones scammers aim for."})
        payee = self.payees.get(pay.get("payee_id") or "", {})
        saved = payee.get("saved_ts")
        if saved is not None and now - saved <= 7 * 86400:
            reasons.append({"code": "NEW_PAYEE", "level": "medium", "title": "New payee",
                            "why": f"The family saved {payee.get('name')} on {_iso(saved)[:10]}, less than a week ago."})
        reasons += self._beneficiary_reasons(payee, now)
        return {"level": self._level(reasons), "reasons": reasons, "duplicate_of": duplicate_of}

    @staticmethod
    def _level(reasons) -> str:
        return "high" if any(x["level"] == "high" for x in reasons) else ("medium" if reasons else "low")

    @staticmethod
    def _beneficiary_reasons(payee: dict, now: float) -> list:
        """The payee's bank account is being changed, or was changed in the last week."""
        if payee.get("pending_account"):
            return [{"code": "BENEFICIARY_CHANGE", "level": "high", "title": "Bank account change on hold",
                     "why": f"A new account for {payee.get('name')} is waiting out its hold. Do not approve a "
                            f"payment to {payee.get('name')} until it is settled."}]
        changed = payee.get("account_changed_ts")
        if changed is not None and now - changed <= 7 * 86400:
            return [{"code": "BENEFICIARY_CHANGE", "level": "high", "title": "Bank account changed recently",
                     "why": f"The saved account for {payee.get('name')} changed on {_iso(changed)[:10]}, less than "
                            f"a week ago. Check the new account with the payee by phone."}]
        return []

    def live_risk(self, r: dict):
        """The request's risk as it stands now: what was found when it was made, plus the checks that can change
        afterwards. Written by code only; it never blocks anything (the gates do) but it is what the family reads.

        BENEFICIARY_CHANGE: the payee's account is on hold or changed within a week.
        APPROVAL_MISMATCH: the bill no longer matches what was asked, i.e. its amount or currency differs from the
        request, its account is not the saved one, or the saved account changed after the request was made.
        """
        base = r.get("risk")
        if base is None or r["kind"] not in ("tuition", "allowance") or r["status"] not in ("pending", "approved"):
            return base
        now = self.clock.ts()
        reasons = list(base["reasons"])
        have = {x["code"] for x in reasons}
        payee = self.payees.get(r.get("payee_id") or "", {})
        if "BENEFICIARY_CHANGE" not in have:
            reasons += self._beneficiary_reasons(payee, now)
        inv = self.invoices.get(r.get("invoice_id") or "")
        why = []
        if inv is not None:
            if inv["currency"] != r["currency"] or q(inv["amount"]) != q(r["amount"]):
                why.append(f"The bill now shows {inv['currency']} {q(inv['amount']):,} but this request is for "
                           f"{r['currency']} {q(r['amount']):,}.")
            if inv.get("account_number") != payee.get("account_number"):
                why.append("The account on the bill is not the payee's saved account.")
        changed = payee.get("account_changed_ts")
        if changed is not None and changed > r.get("created_ts", 0):
            why.append(f"The payee's saved account changed after this request was made ({_iso(changed)[:16]}).")
        if why:
            reasons.append({"code": "APPROVAL_MISMATCH", "level": "high", "title": "Request no longer matches the bill",
                            "why": " ".join(why)})
        return {**base, "level": self._level(reasons), "reasons": reasons}

    def create_request(self, kind: str, pay: dict, case_id: str, bank=None, warnings=(), **extra) -> dict:
        now = self.clock.ts()
        rid = "REQ-" + secrets.token_hex(3).upper()
        warnings = list(warnings)
        risk = None
        if kind in ("tuition", "allowance"):
            risk = self.risk_review(kind, pay, warnings)
            if risk["duplicate_of"]:
                warnings.append(next(x["why"] for x in risk["reasons"] if x["code"] == "DUPLICATE_REQUEST"))
        r = {"id": rid, "kind": kind, "case_id": case_id, "invoice_id": pay.get("invoice_id"),
             "payee_id": pay.get("payee_id"), "payee_name": pay.get("payee_name"), "payee_type": pay.get("payee_type"),
             "amount": pay["amount"], "currency": pay["currency"], "purpose": pay["purpose"],
             "created": _iso(now), "created_ts": now, "expires_ts": now + PAYMENT["family_approval_hours"] * 3600,
             "status": "pending", "bank_review": bank, "warnings": warnings, "risk": risk,
             "decided_at": None, "valid_until_ts": None, "allowance_id": None, **extra}
        self.requests[rid] = r
        return r

    # ------------------------------------------------------------ the family safe word
    # The family agrees a word with its student offline. When someone phones or messages asking the family to approve
    # something urgent, the family asks for the word first. The app cannot tell who is calling; what it does is stop
    # a one-tap approval of the risky requests, make the family type the word, and lock after three wrong tries.
    @staticmethod
    def _norm_word(word) -> str:
        return " ".join(unicodedata.normalize("NFKC", str(word or "")).strip().lower().split())

    @staticmethod
    def _word_hash(word: str, salt: str) -> str:
        return hashlib.pbkdf2_hmac("sha256", word.encode("utf-8"), bytes.fromhex(salt), 120_000).hex()

    def _check_safe_word_lock(self):
        until = self.safe_word_locked_until
        if until and self.clock.ts() < until:
            raise PaymentBlocked("SAFE_WORD_LOCKED", f"Three wrong tries. Locked until {_iso(until)}.")

    def _verify_safe_word(self, given):
        self._check_safe_word_lock()
        word = self._norm_word(given)
        if not word:
            raise PaymentBlocked("SAFE_WORD_REQUIRED", "Type the family's safe word.")
        ok = hmac.compare_digest(self._word_hash(word, self.safe_word["salt"]), self.safe_word["hash"])
        now = self.clock.ts()
        if ok:
            self.safe_word_fails = []
            return
        self.safe_word_fails = [t for t in self.safe_word_fails if now - t < 600] + [now]
        left = PAYMENT["safe_word_max_fails"] - len(self.safe_word_fails)
        if left <= 0:
            self.safe_word_locked_until = now + PAYMENT["safe_word_lock_minutes"] * 60
            self.safe_word_fails = []
            raise PaymentBlocked("SAFE_WORD_LOCKED", f"Too many wrong tries. Locked until "
                                                     f"{_iso(self.safe_word_locked_until)}.")
        raise PaymentBlocked("SAFE_WORD_WRONG", f"Not the safe word. {left} {'try' if left == 1 else 'tries'} left.")

    def set_safe_word(self, word, current=None) -> bool:
        """Set, change or (with an empty word) remove the safe word. Changing or removing needs the current word.
        Returns True if a word is set afterwards."""
        if self.safe_word:
            self._verify_safe_word(current)
        w = self._norm_word(word)
        if not w:
            if not self.safe_word:
                raise PaymentBlocked("INVALID_CHOICE", "There is no safe word to remove.")
            self.safe_word = None
            return False
        if not (4 <= len(w) <= 40) or len(set(w.replace(" ", ""))) < 3:
            raise PaymentBlocked("INVALID_CHOICE", "Choose a safe word of 4 to 40 characters that is not just one "
                                                   "repeated letter.")
        salt = secrets.token_hex(8)
        self.safe_word = {"salt": salt, "hash": self._word_hash(w, salt), "set_at": _iso(self.clock.ts())}
        self.safe_word_fails, self.safe_word_locked_until = [], None
        return True

    def safe_word_reason(self, r: dict):
        """Why approving this request needs the safe word, or None. Rejecting never needs it."""
        if not self.safe_word:
            return None
        if r["kind"] == "account_change":
            return "a changed bank account"
        if r["kind"] in ("tuition", "allowance"):
            if r.get("warnings"):
                return "the request carries warnings"
            live = self.live_risk(r)
            if live and any(x["code"] in ("BENEFICIARY_CHANGE", "APPROVAL_MISMATCH") for x in live["reasons"]):
                return "the bank details or the bill changed"
            if r["currency"] != "CNY" or r["amount"] >= PAYMENT["safe_word_from_cny"]:
                return f"a payment of CNY {PAYMENT['safe_word_from_cny']:,.0f} or more"
        return None

    # ------------------------------------------------------------ a payee the family saves later
    def add_payee(self, name: str, ptype: str, account: str, confirmed: bool) -> dict:
        """The family saves a new payee. It cannot be paid until `new_payee_hold_hours` have passed."""
        name = " ".join(str(name or "").split())[:60]
        digits = re.sub(r"[ -]", "", str(account or ""))
        if not name or not (6 <= len(digits) <= 24 and digits.isdigit()):
            raise PaymentBlocked("INVALID_CHOICE", "Give the payee's name and an account number of 6 to 24 digits.")
        if ptype not in ("institution", "landlord", "merchant", "person_or_agent"):
            raise PaymentBlocked("INVALID_CHOICE", f"'{ptype}' is not a payee type the family can save.")
        if confirmed is not True:
            raise PaymentBlocked("INVALID_CHOICE", "Tick the box to say you checked these details with the payee "
                                                   "yourself (by phone or in person), not from a message or a bill.")
        if self._owner_of(digits) is not None:
            raise PaymentBlocked("INVALID_CHOICE", "That account is already saved for another payee.")
        if len(self.payees) >= 30:
            raise PaymentBlocked("INVALID_CHOICE", "Too many saved payees for the sandbox.")
        pid = "payee_" + secrets.token_hex(3)
        p = {"id": pid, "name": name, "type": ptype, "currency": "CNY", "account_number": digits, "verified": True,
             "saved_by": "family", "saved_on": _iso(self.clock.ts()), "saved_ts": self.clock.ts(),
             "aliases": [name.lower()]}
        self.payees[pid] = p
        return p

    def cooling_left(self, payee: dict):
        """Seconds until a newly saved payee can be paid, or None."""
        ts = payee.get("saved_ts")
        if ts is None or payee["type"] in EXEMPT_TYPES:
            return None
        left = ts + PAYMENT["new_payee_hold_hours"] * 3600 - self.clock.ts()
        return int(left) if left > 0 else None

    # ------------------------------------------------------------ one-day limit raise
    def create_limit_raise(self, cny, day: date, note: str, case_id: str, warnings=()) -> dict:
        v = q(cny)
        if not (self.family_limit < v <= PAYMENT["family_limit_max_cny"]):
            raise PaymentBlocked("LIMIT_OUT_OF_RANGE", f"CNY {v:,.2f}: a raise must be above today's limit "
                                                       f"(CNY {self.family_limit:,.0f}) and at most CNY {PAYMENT['family_limit_max_cny']:,.0f}.")
        today = self.clock.today()
        if not (today <= day <= today + timedelta(days=PAYMENT["limit_raise_days_ahead"])):
            raise PaymentBlocked("DATE_OUT_OF_RANGE", f"{day.isoformat()} is not between {today.isoformat()} and "
                                                      f"{(today + timedelta(days=7)).isoformat()}.")
        return self.create_request("limit_raise", {"amount": v, "currency": "CNY",
                                                   "purpose": f"Raise the daily limit to CNY {v:,.0f} on {day.isoformat()}"},
                                   case_id, warnings=warnings, date=day.isoformat(), note=(note or "")[:300])

    # ------------------------------------------------------------ changed account details
    def create_account_change(self, invoice_id: str, case_id: str) -> dict:
        self.expire()
        inv = self.invoices.get((invoice_id or "").upper())
        if inv is None:
            raise PaymentBlocked("INVOICE_NOT_FOUND", f"There is no stored invoice {invoice_id}.")
        payee = self.payees[inv["payee_id"]]
        acct = inv.get("account_number")
        if not self.reportable_change(inv, payee) or not acct or acct == payee.get("account_number"):
            raise PaymentBlocked("NOT_FOUND", f"{inv['id']} does not report a changed account for a landlord, shop "
                                              f"or university.")
        owner = self._owner_of(acct)
        if owner and owner is not payee:
            raise PaymentBlocked("PAYEE_NOT_VERIFIED", f"{mask_account(acct)} belongs to {owner['name']}, not to "
                                                       f"{payee['name']}.")
        existing = self.pending_request_for(inv["id"], "account_change")
        if existing:
            return existing
        r = self.create_request("account_change", {"invoice_id": inv["id"], "payee_id": payee["id"],
                                                   "payee_name": payee["name"], "payee_type": payee["type"],
                                                   "amount": q(inv["amount"]), "currency": inv["currency"],
                                                   "purpose": f"New bank account for {payee['name']}"},
                                case_id, old_account=mask_account(payee.get("account_number", "")),
                                new_account=mask_account(acct), phone_on_file=payee.get("phone_on_file"),
                                hold_until_ts=None, applied=False)
        self._new_accounts[r["id"]] = acct
        return r

    # ------------------------------------------------------------ family decisions
    def decide(self, request_id: str, approve: bool, hours=None, phone_verified: bool = False, months=None,
               safe_word=None, up_to=None) -> dict:
        self.expire()
        r = self.requests.get(request_id)
        if r is None:
            raise PaymentBlocked("NOT_FOUND", f"No approval request {request_id}.")
        if r["status"] == "expired":
            raise PaymentBlocked("APPROVAL_EXPIRED",
                                 f"{r['id']} expired at {_iso(r['expires_ts'])}; the 24-hour window passed.")
        if r["status"] != "pending":
            raise PaymentBlocked("NOT_FOUND", f"{r['id']} was already {r['status']}.")
        if approve and r["kind"] == "account_change" and not phone_verified:
            raise PaymentBlocked("PHONE_CHECK_REQUIRED",
                                 f"Call {r['payee_name']} on the number on file ({r.get('phone_on_file') or 'none'}), "
                                 f"not a number on the bill, before approving {r['new_account']}.")
        if approve and self.safe_word_reason(r):
            self._verify_safe_word(safe_word)
            r["safe_word_ok"] = True
        if approve and r["kind"] == "allowance":
            hours = self._choice(hours, 1, PAYMENT["allowance_max_hours"], "Validity (hours)")
            months = self._choice(months, 1, PAYMENT["monthly_allowance_max_months"], "Months")
            up_to = self._up_to(up_to, r["amount"])
        now = self.clock.ts()
        r["decided_at"] = _iso(now)
        if not approve:
            r["status"] = "rejected"
            return r
        r["status"] = "approved"
        if r["kind"] == "tuition":
            r["valid_until_ts"] = now + PAYMENT["family_approval_hours"] * 3600
            r["seen_at"] = None
        elif r["kind"] == "limit_raise":
            self.limit_raises[date.fromisoformat(r["date"])] = r["amount"]
        elif r["kind"] == "account_change":
            payee = self.payees[r["payee_id"]]
            r["hold_until_ts"] = now + PAYMENT["account_change_hold_hours"] * 3600
            r["phone_verified"] = True
            payee["pending_account"], payee["hold_until_ts"] = self._new_accounts[r["id"]], r["hold_until_ts"]
        else:
            aid = "ALW-" + secrets.token_hex(3).upper()
            a = {"id": aid, "request_id": r["id"], "case_id": r["case_id"], "payee_id": r["payee_id"],
                 "payee_name": r["payee_name"], "amount": up_to or r["amount"], "quoted": r["amount"],
                 "currency": r["currency"],
                 "invoice_id": r["invoice_id"], "created": _iso(now), "status": "open",
                 "bank_review": r["bank_review"], "used_at": None, "monthly": bool(r.get("monthly"))}
            if a["monthly"]:
                m = months or PAYMENT["monthly_allowance_max_months"]
                a.update(months=m, used_months=[], hours=m * 30 * 24, expires_ts=now + m * 30 * 24 * 3600)
            else:
                h = hours or PAYMENT["allowance_default_hours"]
                a.update(hours=h, expires_ts=now + h * 3600)
            self.allowances[aid] = a
            r["allowance_id"] = aid
        return r

    @staticmethod
    def _up_to(value, quoted: Decimal):
        """An allowance is "up to" an amount: the quote, or a little more the family allows for a price change.
        None means the quote. Anything else must be a whole CNY amount from the quote to the headroom maximum."""
        if value is None or str(value).strip() == "":
            return None
        top = q(quoted * (100 + PAYMENT["allowance_headroom_max_pct"]) / 100)
        try:
            v = q(D(str(value)))
        except Exception:
            v = None
        if v is None or not quoted <= v <= top:
            raise PaymentBlocked("INVALID_CHOICE", f"Up to: '{value}' must be from CNY {quoted:,.2f} to CNY {top:,.2f} "
                                                   f"({PAYMENT['allowance_headroom_max_pct']}% above the quote).")
        return v

    @staticmethod
    def _choice(value, low: int, high: int, label: str):
        """None means the default. Anything else must be a whole number from `low` to `high`; above `high` is
        capped (the documented maximum). Zero, negative or non-numbers are refused, never turned into a default."""
        if value is None:
            return None
        try:
            v = int(value)
        except (TypeError, ValueError):
            v = None
        if v is None or v < low or str(value).strip() not in (str(v), f"{v}.0"):
            raise PaymentBlocked("INVALID_CHOICE", f"{label}: '{value}' is not a whole number from {low}.")
        return min(v, high)

    def tuition_approval(self, request_id: str) -> dict:
        self.expire()
        r = self.requests.get(request_id)
        if r is None or r["kind"] != "tuition":
            raise PaymentBlocked("NOT_FOUND", f"No tuition approval {request_id}.")
        if r["status"] == "expired":
            raise PaymentBlocked("APPROVAL_EXPIRED", "The family's tuition approval is no longer valid.")
        if r["status"] != "approved":
            raise PaymentBlocked("APPROVAL_EXPIRED", f"{request_id} is {r['status']}, not approved.")
        return r

    def check_tuition_approval(self, request_id: str):
        self.tuition_approval(request_id)

    def check_allowance(self, allowance_id: str, payee_id: str, amount: Decimal, month: str = None):
        self.expire()
        a = self.allowances.get(allowance_id)
        if a is None:
            raise PaymentBlocked("ALLOWANCE_NEEDED", "No allowance covers this payment.")
        if a["status"] == "used" or (a.get("monthly") and month in self.monthly_months_used(a["payee_id"])):
            raise PaymentBlocked("ALLOWANCE_USED", f"{a['id']} was already used" + (f" for {month}." if a.get("monthly")
                                                                                     else "."))
        if a["status"] in ("expired", "cancelled"):
            raise PaymentBlocked("ALLOWANCE_EXPIRED", f"{a['id']} is {a['status']}.")
        if a["payee_id"] != payee_id or amount > a["amount"]:
            raise PaymentBlocked("ALLOWANCE_MISMATCH", f"{a['id']} does not match this merchant and amount.")

    def consume_allowance(self, allowance_id: str, month: str = None):
        a = self.allowances[allowance_id]
        if a.get("monthly"):
            a["used_months"].append(month)
        else:
            a["status"] = "used"
        a["used_at"] = _iso(self.clock.ts())

    def cancel_allowance(self, allowance_id: str) -> dict:
        self.expire()
        a = self.allowances.get(allowance_id)
        if a is None or a["status"] != "open":
            raise PaymentBlocked("NOT_FOUND", f"No open allowance {allowance_id}.")
        a["status"] = "cancelled"
        return a

    def ask_cancel(self, item_id: str) -> dict:
        """The student asks the family to cancel an open allowance or a pending allowance request.
        Only a flag: the allowance stays usable until the family cancels it (or rejects the request)."""
        self.expire()
        item = self.allowances.get(item_id)
        if item is None or item["status"] != "open":
            item = self.requests.get(item_id)
            if item is None or item["kind"] != "allowance" or item["status"] != "pending":
                raise PaymentBlocked("NOT_FOUND", f"No open allowance or waiting allowance request {item_id}.")
        item["cancel_asked"] = item.get("cancel_asked") or _iso(self.clock.ts())
        return item

    def mark_paid(self, invoice_id: str):
        if invoice_id:
            self.invoices[invoice_id]["status"] = "paid"

    def expire(self):
        now = self.clock.ts()
        for r in self.requests.values():
            if r["status"] == "pending" and now > r["expires_ts"]:
                r["status"] = "expired"
            elif r["status"] == "approved" and r["valid_until_ts"] and now > r["valid_until_ts"]:
                r["status"] = "expired"
            elif (r["kind"] == "account_change" and r["status"] == "approved" and not r["applied"]
                  and now >= r["hold_until_ts"]):
                # The 24-hour hold has passed: the checked account becomes the saved, verified one.
                payee = self.payees[r["payee_id"]]
                payee["previous_account"] = payee.get("account_number")
                payee["account_changed_ts"] = now
                payee["account_number"], payee["verified"] = self._new_accounts[r["id"]], True
                payee.pop("pending_account", None)
                payee.pop("hold_until_ts", None)
                r["applied"] = True
        for a in self.allowances.values():
            if a["status"] == "open" and now > a["expires_ts"]:
                a["status"] = "expired"

    # ------------------------------------------------------------ family settings
    def set_family_limit(self, cny) -> Decimal:
        low, high = PAYMENT["family_limit_min_cny"], PAYMENT["family_limit_max_cny"]
        v = self._whole(cny)
        if v is None or not (low <= v <= high):
            raise PaymentBlocked("LIMIT_OUT_OF_RANGE", f"CNY {cny}: the family daily limit must be a whole amount "
                                                       f"from CNY {low:,.0f} to {high:,.0f}.")
        self.family_limit = v
        return v

    def set_bank_limit(self, usd) -> Decimal:
        """The bank's daily card limit (simulated bank screen only)."""
        low, high = PAYMENT["bank_limit_min_usd"], PAYMENT["bank_limit_max_usd"]
        v = self._whole(usd)
        if v is None or not (low <= v <= high):
            raise PaymentBlocked("LIMIT_OUT_OF_RANGE", f"USD {usd}: the daily card limit must be a whole amount "
                                                       f"from USD {low:,.0f} to {high:,.0f}.")
        self.bank_limit_usd = v
        return v

    @staticmethod
    def _whole(value):
        """A whole, positive amount typed on a screen, or None."""
        try:
            v = Decimal(str(value))
        except ArithmeticError:
            return None
        return v.quantize(Decimal(1)) if v.is_finite() and v == v.to_integral_value() else None

    def set_document(self, key: str, ready: bool):
        if key not in self.documents:
            raise PaymentBlocked("NOT_FOUND", f"No document '{key}'.")
        self.documents[key]["ready"] = bool(ready)

    # ------------------------------------------------------------ views
    def _xray(self, inv: dict) -> dict:
        """View data for the invoice X-ray. It re-reads what Gate 1 finds and never changes it."""
        payee = self.payees[inv["payee_id"]]
        code = None
        if inv["status"] != "paid":
            try:
                self.gate1(inv["id"])
            except PaymentBlocked as b:
                code = b.code
        owner = self._owner_of(inv.get("account_number"))
        owner_name = owner["name"] if owner and owner is not payee else None
        return xray.build(inv, payee, owner_name, code)

    def _doc(self, inv: dict) -> dict:
        """View data for the invoice as printed: issuer, bill-to, lines and bank. Account numbers stay masked
        (the X-ray carries the positions). The bank shown is the one that owns the account on the bill."""
        payee = self.payees[inv["payee_id"]]
        owner = self._owner_of(inv.get("account_number")) or payee
        return {"issuer": inv.get("issuer") or payee["name"], "address": payee.get("address"),
                "bill_to": self.owner.get("display_name"), "student_id": self.owner.get("student_id"),
                "school": self.owner.get("university"), "issued": inv.get("issued"),
                "lines": [{"item": l["item"], "amount": q(l["amount"])} for l in inv.get("lines", [])]
                or [{"item": inv["purpose"], "amount": q(inv["amount"])}],
                "bank_name": inv.get("bank_name") or owner.get("bank_name")}

    def snapshot(self) -> dict:
        self.expire()
        now = self.clock.ts()

        def left(ts):
            return max(0, int(ts - now)) if ts else None

        def req_left(r):
            if r["status"] == "pending":
                return left(r["expires_ts"])
            if r["kind"] == "account_change" and not r.get("applied"):
                return left(r.get("hold_until_ts"))
            return left(r["valid_until_ts"])

        return {
            "family_name": self.family_name,
            "family_limit": self.family_limit,
            "family_limit_today": self.family_limit_today(),
            "family_spent_today": self.spent_today("family"),
            "family_remaining": self.family_remaining(),
            "limit_raises": [{"date": d.isoformat(), "cny": v} for d, v in sorted(self.limit_raises.items())],
            "card_spent_today": self.spent_today("card"),
            "bank_limit_usd": self.bank_limit_usd,
            "bank_limit_range_usd": [PAYMENT["bank_limit_min_usd"], PAYMENT["bank_limit_max_usd"]],
            "family_limit_range": [PAYMENT["family_limit_min_cny"], PAYMENT["family_limit_max_cny"]],
            "messages": self.messages,
            "bank_log": self.bank_log,
            "bank_limit_cny": self.bank_limit_cny(),
            "exempt_cap_cny": PAYMENT["exempt_cap_cny"],
            "safe_word": {"set": bool(self.safe_word), "from_cny": PAYMENT["safe_word_from_cny"],
                          "locked_seconds_left": left(self.safe_word_locked_until)},
            "new_payee_hold_hours": PAYMENT["new_payee_hold_hours"],
            "payees": [{"id": p["id"], "name": p["name"], "type": p["type"], "verified": p.get("verified", False),
                        "saved_on": p.get("saved_on"), "cooling_seconds_left": self.cooling_left(p),
                        "account": mask_account(p["account_number"]) if p.get("account_number") else None,
                        "on_hold": mask_account(p["pending_account"]) if p.get("pending_account") else None,
                        "hold_seconds_left": left(p.get("hold_until_ts"))}
                       for p in self.payees.values()],
            "invoices": [{"id": i["id"], "payee": self.payees[i["payee_id"]]["name"], "kind": i.get("kind"),
                          "purpose": i["purpose"], "amount": q(i["amount"]), "currency": i["currency"],
                          "due": i.get("due"), "status": i["status"],
                          "account": mask_account(i["account_number"]) if i.get("account_number") else None,
                          "account_ok": i.get("account_number") == self.payees[i["payee_id"]].get("account_number"),
                          "lab": bool(i.get("lab")), "via_message": bool(i.get("arrives_as")),
                          "reported": i.get("reported"), "source": i.get("source"), "sent_by": i.get("sent_by"), "xray": self._xray(i), "doc": self._doc(i)}
                         for i in self.invoices.values()],
            "documents": [{"key": k, **v} for k, v in self.documents.items()],
            "requests": [{**{k: v for k, v in r.items() if not k.endswith("_ts")}, "risk": self.live_risk(r),
                          "seconds_left": req_left(r),
                          "needs_safe_word": self.safe_word_reason(r) if r["status"] == "pending" else None}
                         for r in self.requests.values()],
            "allowances": [{**{k: v for k, v in a.items() if not k.endswith("_ts")},
                            "seconds_left": left(a["expires_ts"]) if a["status"] == "open" else None}
                           for a in self.allowances.values()],
        }
