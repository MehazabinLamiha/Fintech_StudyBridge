"""Bills by message or typed in by the student (inbox.py), and the bank's own daily card limit."""
import json
import tempfile
import unittest
from decimal import Decimal as D
from pathlib import Path

from studybridge import state
from studybridge.reasons import PaymentBlocked
from tests.test_payments import make_sandbox


class TestBillsByMessage(unittest.TestCase):
    def setUp(self):
        self.sb = make_sandbox()
        self.book = self.sb.agent.book

    def send(self, template):
        return self.sb.act("operator", "send_message", {"template": template})

    def pay(self, inv):
        return self.sb.act("student", "chat", {"message": f"pay {inv}"})

    def test_a_payees_own_channel_files_the_bill_and_the_usual_route_follows(self):
        self.assertEqual(self.send("uni_tuition").data["invoice_id"], "BILL-0001")
        self.assertEqual(self.pay("BILL-0001").code, "AWAITING_FAMILY")           # tuition: the family approves
        self.send("uni_fee")
        self.assertEqual(self.pay("BILL-0002").code, "READY_TO_CONFIRM")          # small fee within the family limit

    def test_a_shop_quote_by_message_goes_family_then_bank(self):
        self.send("shop_quote")
        r = self.sb.act("student", "chat", {"message": "request an allowance for BILL-0001"})
        self.assertEqual(r.code, "ALLOWANCE_REQUESTED")
        case = self.sb.agent.cases[r.case_id]
        self.assertEqual(case["bank"]["decision"], "approved")                     # CNY 4,200 is above USD 300 a day

    def test_an_unknown_sender_waits_and_gate1_still_refuses_its_account(self):
        r = self.send("fake_uni")
        self.assertIsNone(r.data["invoice_id"])
        self.assertEqual(self.sb.act("student", "add_message_bill", {"id": r.data["message_id"]}).code, "OK")
        self.assertEqual(self.sb.act("student", "add_message_bill", {"id": r.data["message_id"]}).code,
                         "INVALID_CHOICE")                                         # only once
        before = len(self.sb.agent.wallet.transactions)
        self.assertTrue(self.pay("BILL-0001").blocked)
        self.assertEqual(len(self.sb.agent.wallet.transactions), before)

    def test_each_sample_message_arrives_once(self):
        self.send("uni_tuition")
        r = self.send("uni_tuition")
        self.assertEqual(r.code, "INVALID_CHOICE")
        self.assertIn("BILL-0001", r.text)
        self.assertEqual(len([m for m in self.book.messages if m["template"] == "uni_tuition"]), 1)

    def test_the_sample_scam_bills_arrive_as_messages_not_in_bills(self):
        seeded = [m for m in self.book.messages if m.get("attached")]
        self.assertEqual(sorted(m["invoice_id"] for m in seeded),
                         ["INV-0004", "INV-0005", "INV-0006", "INV-0009", "INV-0011", "RENT-2026-11B"])
        self.assertTrue(all(not m["official"] for m in seeded))
        bills = {i["id"]: i["via_message"] for i in self.sb.snapshot()["book"]["invoices"]}
        self.assertFalse(bills["INV-0003"])
        self.assertTrue(bills["INV-0009"])
        self.assertEqual(self.sb.act("student", "chat", {"message": "pay invoice INV-0009"}).code, "ACCOUNT_CHANGED")

    def test_a_message_reported_as_scam_locks_its_bill_until_undone(self):
        msg = next(m for m in self.book.messages if m.get("invoice_id") == "INV-0005")
        r = self.sb.act("student", "report_message", {"id": msg["id"]})
        self.assertEqual(r.code, "OK")
        self.assertEqual(self.sb.act("student", "chat", {"message": "pay invoice INV-0005"}).code, "REPORTED_AS_SCAM")
        case = self.sb.agent.cases[r.case_id]
        self.assertEqual((case["kind"], case["outcome"]), ("payment", "REPORTED_AS_SCAM"))     # the family sees it
        self.assertIn("INV-0005", self.sb.impact["scams"])                                  # counted once
        self.assertEqual(self.sb.act("student", "report_message", {"id": msg["id"]}).code, "INVALID_CHOICE")
        self.assertEqual(self.sb.act("family", "report_message", {"id": msg["id"]}).code, "ACTOR_NOT_PERMITTED")
        self.assertEqual(self.sb.act("student", "report_message", {"id": msg["id"], "undo": True}).code, "OK")
        self.assertEqual(self.sb.act("student", "chat", {"message": "pay invoice INV-0005"}).code, "PAYEE_NOT_VERIFIED")

    def test_a_reported_message_bill_cannot_be_added_to_bills(self):
        sent = self.send("fake_uni")
        mid = sent.data["message_id"]
        self.sb.act("student", "report_message", {"id": mid})
        self.assertEqual(self.sb.act("student", "add_message_bill", {"id": mid}).code, "INVALID_CHOICE")

    def test_only_the_right_screen_can_do_each_action(self):
        self.assertEqual(self.sb.act("student", "send_message", {"template": "uni_fee"}).code, "ACTOR_NOT_PERMITTED")
        self.assertEqual(self.sb.act("family", "add_bill", {}).code, "ACTOR_NOT_PERMITTED")
        self.assertEqual(self.send("nope").code, "INVALID_CHOICE")


class TestBillsTypedByStudent(unittest.TestCase):
    def setUp(self):
        self.sb = make_sandbox()

    def add(self, **spec):
        base = {"payee_id": "techmart", "kind": "quote", "amount": "350", "purpose": "Desk lamp"}
        return self.sb.act("student", "add_bill", {**base, **spec})

    def test_the_account_on_the_bill_decides(self):
        self.assertEqual(self.add(account_number="1234567890").code, "OK")
        self.assertTrue(self.sb.act("student", "chat", {"message": "pay BILL-0001"}).blocked)
        self.assertEqual(self.add(account_mode="saved").code, "OK")
        self.assertEqual(self.sb.act("student", "chat", {"message": "pay BILL-0002"}).code, "READY_TO_CONFIRM")

    def test_only_saved_university_landlord_or_shop(self):
        self.assertEqual(self.add(payee_id="bright_future", account_mode="saved").code, "INVALID_CHOICE")
        self.assertEqual(self.add(payee_id="someone_new", account_mode="saved").code, "INVALID_CHOICE")
        self.assertEqual(self.add(amount="-5", account_mode="saved").code, "INVALID_CHOICE")

    def test_the_screen_never_gets_a_full_account_number(self):
        self.add(account_number="9988776655443322")
        self.sb.act("operator", "send_message", {"template": "fake_uni"})
        snap = json.dumps(self.sb.snapshot(), default=str)
        for num in ("9988776655443322", "6222020200998877661"):
            self.assertNotIn(num, snap)


class TestBankLimit(unittest.TestCase):
    def test_only_the_bank_sets_it_within_range(self):
        sb = make_sandbox()
        self.assertEqual(sb.act("family", "set_bank_limit", {"usd": 500}).code, "ACTOR_NOT_PERMITTED")
        self.assertEqual(sb.act("student", "set_bank_limit", {"usd": 500}).code, "ACTOR_NOT_PERMITTED")
        for bad in (99, 1001, 250.5, "x"):
            self.assertEqual(sb.act("bank", "set_bank_limit", {"usd": bad}).code, "LIMIT_OUT_OF_RANGE", bad)
        self.assertEqual(sb.act("bank", "set_bank_limit", {"usd": 100}).code, "SETTING_CHANGED")
        self.assertEqual(sb.agent.book.bank_limit_usd, D("100"))

    def test_a_lower_limit_sends_rent_to_bank_review(self):
        ask = "request a monthly allowance for RENT-2026-11"                # CNY 1,800 ≈ USD 254
        sb = make_sandbox()
        r = sb.act("student", "chat", {"message": ask})
        self.assertIsNone(sb.agent.cases[r.case_id].get("bank"))            # within USD 300: no review
        sb = make_sandbox()
        sb.act("bank", "set_bank_limit", {"usd": 200})
        r = sb.act("student", "chat", {"message": ask})
        self.assertEqual(r.code, "ALLOWANCE_REQUESTED")
        self.assertEqual(sb.agent.cases[r.case_id]["bank"]["decision"], "approved")


    def test_the_bank_logs_approved_and_rejected_reviews(self):
        sb = make_sandbox()
        sb.act("student", "chat", {"message": "request an allowance for Q-TM-0042"})
        book = sb.agent.book
        self.assertEqual([r["decision"] for r in book.bank_log], ["approved"])
        book.invoices["Q-HG-0007"]["purpose"] = ""                             # a quote that says nothing
        with self.assertRaises(PaymentBlocked):
            book.bank_review({"invoice_id": "Q-HG-0007", "amount": D("3000"), "currency": "CNY"})
        self.assertEqual(book.bank_log[-1]["decision"], "rejected")
        self.assertIn("Purpose stated", book.bank_log[-1]["reason"])


class TestSaved(unittest.TestCase):
    def test_messages_and_bank_limit_survive_a_restart(self):
        sb = make_sandbox()
        sb.act("operator", "send_message", {"template": "fake_uni"})
        sb.act("bank", "set_bank_limit", {"usd": 450})
        path = Path(tempfile.mkdtemp()) / "state.json"
        state.save_file(sb, path)
        sb2 = make_sandbox()
        state.load(sb2, json.loads(path.read_text()))
        self.assertEqual(sb2.agent.book.bank_limit_usd, D("450"))
        msg = next(m for m in sb2.agent.book.messages if m["template"] == "fake_uni")
        self.assertEqual(sb2.act("student", "add_message_bill", {"id": msg["id"]}).code, "OK")


if __name__ == "__main__":
    unittest.main()
