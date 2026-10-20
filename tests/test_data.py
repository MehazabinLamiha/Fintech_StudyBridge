"""Checks on the fictional sample data (data/sample_profile.json).

Ported from Nura's data tests (written for the v0.1 data format) to the v0.3 format. They keep the
data honest: every invoice points at a real payee, the code each invoice gets follows from the data
alone, every bad invoice has exactly one problem, and the numbers the stories rely on still hold.
"""
import json
import pathlib
import re
import unittest
from collections import Counter
from datetime import date, datetime
from decimal import Decimal as D

from studybridge import DEFAULT_PROFILE
from studybridge.clock import SandboxClock
from studybridge.config import EXEMPT_TYPES, LIMITS, PAYEE_TYPES, PAYMENT
from studybridge.money import convert_mid, to_usd
from studybridge.payments import DOC_ID, PaymentBook
from studybridge.reasons import REASONS, STATUS, PaymentBlocked
from studybridge.security.guard import looks_like_injection, pressure_signals
from studybridge.stories import STORIES

PROFILE = json.loads(DEFAULT_PROFILE.read_text(encoding="utf-8"))
PAYEES = {p["id"]: p for p in PROFILE["payees"]}
INV = {i["id"]: i for i in PROFILE["invoices"]}
DOCS = PROFILE["documents"]
RUN_DAY = date(2026, 10, 13)          # the sandbox clock start used by tests, stories and the demo
TESTS = pathlib.Path(__file__).parent


def expected_from_data(inv):
    """Re-derive the Gate 1 code from the raw data, independently of payments.py."""
    payee = PAYEES[inv["payee_id"]]
    if inv["status"] == "paid":
        return "INVOICE_ALREADY_PAID"
    if inv.get("account_number") != payee.get("account_number") or not payee["verified"]:
        reportable = payee["type"] in ("landlord", "merchant") or (
            payee["type"] == "institution" and inv.get("claims_new_account") is True)
        return "ACCOUNT_CHANGED" if reportable else "PAYEE_NOT_VERIFIED"
    if inv.get("valid_until") and date.fromisoformat(inv["valid_until"]) < RUN_DAY:
        return "QUOTE_EXPIRED"
    if inv["kind"] == "tuition" and payee["type"] != "institution":
        return "PAYEE_NOT_VERIFIED"
    if any(not DOCS[d]["ready"] for d in inv.get("required_docs", [])):
        return "DOCS_MISSING"
    return None


def problems(inv):
    payee = PAYEES[inv["payee_id"]]
    return [inv["status"] == "paid",
            inv.get("account_number") != payee.get("account_number") or not payee["verified"],
            inv["kind"] == "tuition" and payee["type"] != "institution",
            any(not DOCS[d]["ready"] for d in inv.get("required_docs", [])),
            bool(inv.get("valid_until")) and date.fromisoformat(inv["valid_until"]) < RUN_DAY]


class TestPayees(unittest.TestCase):
    def test_every_payee_has_the_required_fields(self):
        for p in PAYEES.values():
            self.assertIn(p["type"], PAYEE_TYPES, p["id"])
            self.assertIsInstance(p["verified"], bool, p["id"])
            self.assertEqual(p["currency"], "CNY", p["id"])
            self.assertTrue(p["name"], p["id"])

    def test_aliases_are_not_shared(self):
        seen = Counter(a.lower() for p in PAYEES.values() for a in p.get("aliases", []) + [p["name"]])
        self.assertEqual([a for a, n in seen.items() if n > 1], [])

    def test_account_numbers_are_unique_digits(self):
        numbers = [p["account_number"] for p in PAYEES.values() if "account_number" in p]
        self.assertEqual(len(numbers), len(set(numbers)))
        self.assertTrue(all(n.isdigit() and len(n) >= 12 for n in numbers))

    def test_food_and_qr_payees_have_no_account(self):
        # Name-only payees: they are capped because there is no account or invoice to check.
        for p in PAYEES.values():
            if p["type"] in EXEMPT_TYPES:
                self.assertNotIn("account_number", p, p["id"])

    def test_phone_on_file_for_payees_that_can_change_account(self):
        # The changed-account check calls this number, never a number on the bill.
        for p in PAYEES.values():
            if p["type"] in ("institution", "landlord", "merchant"):
                self.assertRegex(p.get("phone_on_file", ""), r"^\+\d[\d ]+$", p["id"])

    def test_agent_is_saved_by_the_family(self):
        agents = [p for p in PAYEES.values() if p["type"] == "person_or_agent"]
        self.assertTrue(agents)
        self.assertTrue(all(p.get("saved_by") == "family" for p in agents))


class TestInvoices(unittest.TestCase):
    def test_references_resolve(self):
        for i in INV.values():
            self.assertIn(i["payee_id"], PAYEES, i["id"])
            for d in i.get("required_docs", []):
                self.assertIn(d, DOCS, i["id"])

    def test_ids_are_unique_and_readable_by_the_parser(self):
        self.assertEqual(len(INV), len(PROFILE["invoices"]))
        for iid in INV:
            self.assertEqual([m.group() for m in DOC_ID.finditer(f"pay {iid} now")], [iid])

    def test_amounts_currency_and_kind(self):
        for i in INV.values():
            self.assertGreater(D(i["amount"]), 0, i["id"])
            self.assertEqual(i["currency"], "CNY", i["id"])
            self.assertIn(i["kind"], ("tuition", "fee", "bill", "quote"), i["id"])

    def test_payee_types_that_need_an_invoice_have_one(self):
        for p in PAYEES.values():
            if PAYEE_TYPES[p["type"]] and p["type"] != "person_or_agent":
                self.assertTrue(any(i["payee_id"] == p["id"] for i in INV.values()), p["id"])

    def test_gate1_code_follows_from_the_data(self):
        book = PaymentBook(PROFILE, SandboxClock(datetime(2026, 10, 13, 9, 0)))
        for iid, inv in INV.items():
            with self.subTest(invoice=iid):
                try:
                    book.gate1(iid)
                    got = None
                except PaymentBlocked as b:
                    got = b.code
                self.assertEqual(got, expected_from_data(inv))

    def test_each_bad_invoice_has_one_problem(self):
        # A bad invoice fails for exactly one reason, so a test failure points at one cause.
        for i in INV.values():
            if expected_from_data(i):
                self.assertEqual(sum(problems(i)), 1, i["id"])

    def test_open_invoices_are_due_on_or_after_the_run_day(self):
        for i in INV.values():
            if i["status"] == "open" and i.get("due"):
                self.assertGreaterEqual(date.fromisoformat(i["due"]), RUN_DAY, i["id"])

    def test_one_expired_quote_for_the_bank_review(self):
        expired = [i["id"] for i in INV.values() if i.get("valid_until")
                   and date.fromisoformat(i["valid_until"]) < RUN_DAY]
        self.assertEqual(expired, ["Q-TM-0050"])


class TestStoryNumbers(unittest.TestCase):
    """The amounts the stories and the plan rely on."""

    def test_yearly_tuition_is_one_invoice_under_the_hard_cap(self):
        inv = INV["INV-0003"]
        self.assertEqual((inv["kind"], D(inv["amount"])), ("tuition", D("22800.00")))
        self.assertLess(convert_mid(D(inv["amount"]), "CNY", "BDT"), LIMITS["tuition_per_tx_home"])
        last_year = INV["INV-0002"]
        self.assertEqual((last_year["status"], last_year["amount"]), ("paid", inv["amount"]))

    def test_rent_needs_an_allowance_but_no_bank_review(self):
        rent = D(INV["RENT-2026-11"]["amount"])
        self.assertGreater(rent, PAYMENT["family_limit_default_cny"])     # a family may raise its own limit above it
        self.assertLess(to_usd(rent, "CNY"), PAYMENT["bank_daily_limit_usd"])

    def test_rent_bills_are_in_different_months(self):
        a, b = INV["RENT-2026-11"], INV["RENT-2026-12"]
        self.assertEqual((a["payee_id"], a["amount"]), (b["payee_id"], b["amount"]))
        self.assertNotEqual(a["due"][:7], b["due"][:7])

    def test_fridge_needs_a_bank_review_and_a_same_price_rival_exists(self):
        fridge, rival = INV["Q-TM-0042"], INV["Q-HG-0007"]
        self.assertGreater(to_usd(D(fridge["amount"]), "CNY"), PAYMENT["bank_daily_limit_usd"])
        self.assertEqual(fridge["amount"], rival["amount"])
        self.assertNotEqual(fridge["payee_id"], rival["payee_id"])

    def test_bad_examples_are_present(self):
        accounts = {p.get("account_number") for p in PAYEES.values()}
        self.assertEqual(INV["INV-0004"]["account_number"][:-2], PAYEES["sample_university"]["account_number"][:-2])
        self.assertEqual(INV["INV-0005"]["account_number"], PAYEES["bright_future"]["account_number"])
        # Personal wallet (from Nura's data): on no saved payee, and the invoice does not claim a bank change.
        self.assertNotIn(INV["INV-0006"]["account_number"], accounts)
        self.assertNotIn("claims_new_account", INV["INV-0006"])
        # University "changed bank details" (from Nura's data): the invoice claims it; the saved account is unchanged.
        self.assertTrue(INV["INV-0009"]["claims_new_account"])
        self.assertNotIn(INV["INV-0009"]["account_number"], accounts)
        self.assertTrue(looks_like_injection(INV["INV-0008"]["memo"]))
        self.assertIn("personal wallet", INV["INV-0006"]["memo"])
        self.assertTrue(pressure_signals(INV["INV-0011"]["memo"]))
        self.assertTrue(any(looks_like_injection(t["memo"]) for t in PROFILE["transactions"]))

    def test_every_invoice_in_a_story_exists(self):
        ids = {m.group().upper() for s in STORIES for st in s.steps
               for m in DOC_ID.finditer(json.dumps(st["args"]))}
        unknown = ids - set(INV)
        self.assertEqual(unknown, {"INV-9999"})        # story C2: an unknown id on purpose


class TestCoverage(unittest.TestCase):
    def test_every_reason_and_status_code_is_exercised(self):
        src = "".join(p.read_text(encoding="utf-8") for p in TESTS.glob("test_*.py") if p.name != "test_data.py")
        src += json.dumps([[st["expect"] for st in s.steps] for s in STORIES])
        missing = [c for c in list(REASONS) + list(STATUS) if not re.search(r"\b" + c + r"\b", src)]
        self.assertEqual(missing, [])


    def test_every_refusal_says_who_can_change_it(self):
        from studybridge.reasons import WHO, WHO_TEXT
        self.assertEqual(sorted(set(REASONS) - set(WHO)), [])
        self.assertEqual(sorted(set(WHO) - set(REASONS)), [])
        self.assertTrue(set(WHO.values()) <= set(WHO_TEXT))


class TestFictional(unittest.TestCase):
    def test_file_is_labelled_fictional(self):
        self.assertIn("Fictional", PROFILE["_note"])
        self.assertIn("sample", PROFILE["owner"]["display_name"])
        self.assertIn("sample", PROFILE["family"]["name"])

    def test_readme_exists(self):
        self.assertIn("fictional", (DEFAULT_PROFILE.parent / "README.md").read_text(encoding="utf-8").lower())


if __name__ == "__main__":
    unittest.main()
