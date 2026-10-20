"""The deadline database and scheduler, the AI-written advice, and the beneficiary-change / approval-mismatch reasons."""
import tempfile
import threading
import unittest
from decimal import Decimal as D
from pathlib import Path

from studybridge import DEFAULT_PROFILE
from studybridge.deadlines import DeadlineStore
from studybridge.sandbox import Sandbox
from studybridge.security.audit import AuditLog
from studybridge.security.permissions import Tier
from tests.test_payments import START, CountingLLM, make_sandbox


def reqs(sb):
    return {r["id"]: r for r in sb.snapshot()["book"]["requests"]}


class TestDeadlineDatabaseAndScheduler(unittest.TestCase):
    def test_clock_moves_run_the_scheduler_and_each_reminder_is_raised_once(self):
        sb = make_sandbox()
        self.assertEqual(sb.snapshot()["guardian"]["reminders"], [])          # 13 Oct: nothing due soon
        sb.act("operator", "advance_clock", {"hours": 24 * 24})              # 6 Nov: "soon"
        rem = sb.snapshot()["guardian"]["reminders"]
        self.assertEqual([r["level"] for r in rem], ["soon"])
        sb.act("operator", "run_scheduler")                                   # same day again: no duplicate
        sb.act("operator", "advance_clock", {"hours": 1})
        self.assertEqual(len(sb.snapshot()["guardian"]["reminders"]), 1)
        sb.act("operator", "advance_clock", {"hours": 24 * 5})               # 11 Nov: "now"
        sb.act("operator", "advance_clock", {"hours": 24 * 9})               # 20 Nov: overdue
        self.assertEqual(sorted(r["level"] for r in sb.snapshot()["guardian"]["reminders"]),
                         ["now", "overdue", "soon"])

    def test_deadline_rows_are_stored_and_reminders_are_audited(self):
        sb = make_sandbox()
        sb.act("operator", "advance_clock", {"hours": 24 * 24})
        rows = sb.deadlines.deadlines()
        self.assertEqual([r["invoice_id"] for r in rows], ["INV-0003"])
        self.assertEqual(rows[0]["level"], "soon")
        self.assertEqual(rows[0]["send_by"], "2026-11-09")
        events = [l for l in sb.audit.path.read_text(encoding="utf-8").splitlines() if "reminder_created" in l]
        self.assertEqual(len(events), 1)
        self.assertTrue(sb.audit.verify()["ok"])

    def test_got_it_marks_a_reminder_seen_and_pays_nothing(self):
        sb = make_sandbox()
        sb.act("operator", "advance_clock", {"hours": 24 * 24})
        rid = sb.snapshot()["guardian"]["reminders"][0]["id"]
        before = dict(sb.agent.wallet.balances)
        self.assertEqual(sb.act("student", "ack_reminder", {"id": rid}).code, "SETTING_CHANGED")
        self.assertEqual(sb.snapshot()["guardian"]["reminders"], [])
        self.assertEqual(sb.agent.wallet.balances, before)
        self.assertEqual(sb.act("student", "ack_reminder", {"id": rid}).code, "INVALID_CHOICE")   # already seen
        self.assertEqual(sb.act("student", "ack_reminder", {"id": "nope"}).code, "INVALID_CHOICE")

    def test_a_paid_invoice_leaves_the_deadline_table(self):
        sb = make_sandbox()
        sb.act("operator", "advance_clock", {"hours": 24 * 24})
        sb.agent.book.invoices["INV-0003"]["status"] = "paid"
        sb.act("operator", "run_scheduler")
        self.assertEqual(sb.deadlines.deadlines(), [])

    def test_reset_clears_the_store_but_a_restart_keeps_a_database_file(self):
        sb = make_sandbox()
        sb.act("operator", "advance_clock", {"hours": 24 * 24})
        sb.act("operator", "reset")
        self.assertEqual(sb.deadlines.deadlines(), [])
        self.assertEqual(sb.deadlines.reminders(), [])
        db = Path(tempfile.mkdtemp()) / "sb.db"
        a = Sandbox(DEFAULT_PROFILE, AuditLog(Path(tempfile.mkdtemp()) / "a.jsonl"), tier=Tier.TRANSACT, start=START,
                    db_path=db)
        a.act("operator", "advance_clock", {"hours": 24 * 24})
        a.deadlines.close()
        b = Sandbox(DEFAULT_PROFILE, AuditLog(Path(tempfile.mkdtemp()) / "b.jsonl"), tier=Tier.TRANSACT, start=START,
                    db_path=db)
        self.assertEqual([r["level"] for r in b.deadlines.reminders()], ["soon"])      # survived the restart
        b.act("operator", "advance_clock", {"hours": 1})
        self.assertEqual(len(b.deadlines.reminders()), 1)                                # and is not raised again

    def test_only_the_right_actors_may_use_the_new_actions(self):
        sb = make_sandbox()
        for actor, action in (("family", "guardian_advice"), ("student", "run_scheduler"), ("family", "ack_reminder")):
            self.assertEqual(sb.act(actor, action, {"id": "RMD-1"}).code, "ACTOR_NOT_PERMITTED", (actor, action))

    def test_the_web_scheduler_thread_raises_reminders_under_the_server_lock(self):
        from studybridge.web import run_scheduler
        sb = make_sandbox()
        sb.agent.clock.advance(hours=24 * 24)               # time moved without the screen calling the check
        self.assertEqual(sb.deadlines.reminders(), [])
        lock, stop = threading.Lock(), threading.Event()
        t = threading.Thread(target=run_scheduler, args=(sb, lock, stop, 0.02), daemon=True)
        t.start()
        for _ in range(100):
            if sb.deadlines.reminders():
                break
            stop.wait(0.02)
        stop.set()
        t.join(2)
        self.assertEqual([r["level"] for r in sb.deadlines.reminders()], ["soon"])

    def test_store_unit_clear_and_ack(self):
        st = DeadlineStore()
        g = {"items": [{"invoice_id": "X", "amount": D("1"), "currency": "USD", "due_date": "2026-11-01",
                        "send_by": "2026-10-30", "level": "now"}], "funding_balance": D("0"),
             "funding_needed": D("5"), "funding_gap": D("5")}
        self.assertEqual(len(st.sync(g, "2026-10-29T09:00")), 1)
        self.assertEqual(st.sync(g, "2026-10-29T09:05"), [])
        self.assertIn("short by", st.reminders()[0]["text"])
        st.clear()
        self.assertEqual((st.deadlines(), st.reminders()), ([], []))


ADVICE_OK = ("Send {days_left} days ahead if you can. Ask the family to approve {invoice} soon, and top up "
             "{funding_gap_bdt} BDT if needed.")


class TestGuardianAdvice(unittest.TestCase):
    def test_code_advice_when_qwen_is_off_is_stored_and_shown(self):
        sb = make_sandbox()
        r = sb.act("student", "guardian_advice")
        self.assertEqual(r.data["advice"]["source"], "code")
        self.assertIn("INV-0003", r.text)
        self.assertEqual(sb.snapshot()["guardian"]["advice"]["text"], r.text)

    def test_qwen_advice_has_numbers_filled_by_code_and_is_cached(self):
        llm = CountingLLM(text="Ask the family to approve INV-0003 well before 2026-11-09. "
                               "You have {days_left} days left, so do not wait.")
        sb = make_sandbox(llm)
        r = sb.act("student", "guardian_advice")
        self.assertEqual(r.data["advice"]["source"], "qwen")
        self.assertIn("days left", r.text)
        self.assertNotIn("{", r.text)
        again = sb.act("student", "guardian_advice")
        self.assertEqual(again.text, r.text)
        self.assertEqual(len(llm.calls), 1)                       # same facts: the model was not asked twice
        self.assertIn("INV-0003", llm.calls[0])

    def test_typed_digits_and_false_claims_are_cut_and_fall_back_to_code(self):
        llm = CountingLLM(text="Your payment of 99999 BDT has been sent and is guaranteed.")
        sb = make_sandbox(llm)
        r = sb.act("student", "guardian_advice")
        self.assertEqual(r.data["advice"]["source"], "code")
        self.assertNotIn("99999", r.text)
        self.assertNotIn("guaranteed", r.text)

    def test_a_model_error_falls_back_to_code_advice(self):
        from studybridge.llm import LLMError

        class Broken(CountingLLM):
            def chat_text(self, system, user):
                raise LLMError("timeout")
        sb = make_sandbox(Broken())
        r = sb.act("student", "guardian_advice")
        self.assertEqual(r.data["advice"]["source"], "code")

    def test_new_facts_get_new_advice(self):
        llm = CountingLLM(text="Ask the family to approve INV-0003 now.")
        sb = make_sandbox(llm)
        sb.act("student", "guardian_advice")
        sb.act("operator", "advance_clock", {"hours": 24 * 24})
        self.assertIsNone(sb.snapshot()["guardian"]["advice"])    # facts changed: old advice is not shown
        sb.act("student", "guardian_advice")
        self.assertEqual(len(llm.calls), 2)

    def test_advice_never_moves_money(self):
        sb = make_sandbox(CountingLLM(text="Pay now."))
        before = (dict(sb.agent.wallet.balances), dict(sb.agent.book.requests))
        sb.act("student", "guardian_advice")
        self.assertEqual((dict(sb.agent.wallet.balances), dict(sb.agent.book.requests)), before)


class TestBeneficiaryAndMismatchReasons(unittest.TestCase):
    def codes(self, sb, rid):
        return [x["code"] for x in reqs(sb)[rid]["risk"]["reasons"]]

    def test_an_account_change_on_hold_is_a_high_risk_reason(self):
        sb = make_sandbox()
        r = sb.act("student", "chat", {"message": "request an allowance for RENT-2026-11"})
        self.assertEqual(r.code, "ALLOWANCE_REQUESTED")
        self.assertEqual(reqs(sb)[r.request_id]["risk"]["level"], "low")
        c = sb.act("student", "submit_account_change", {"invoice_id": "RENT-2026-11B"})
        sb.act("family", "decide", {"request_id": c.request_id, "approve": True, "phone_verified": True})
        risk = reqs(sb)[r.request_id]["risk"]
        self.assertEqual(risk["level"], "high")
        self.assertIn("BENEFICIARY_CHANGE", self.codes(sb, r.request_id))
        sb.act("operator", "advance_clock", {"hours": 1})
        book = sb.agent.book                                                  # the hold ends while the request is open
        payee = book.payees[book.requests[r.request_id]["payee_id"]]
        payee["account_changed_ts"], payee["pending_account"] = book.clock.ts(), None
        codes = self.codes(sb, r.request_id)
        self.assertIn("BENEFICIARY_CHANGE", codes)
        self.assertIn("APPROVAL_MISMATCH", codes)                              # the account moved after the request

    def test_a_request_made_after_the_change_names_the_recent_change(self):
        sb = make_sandbox()
        c = sb.act("student", "submit_account_change", {"invoice_id": "RENT-2026-11B"})
        sb.act("family", "decide", {"request_id": c.request_id, "approve": True, "phone_verified": True})
        sb.act("operator", "advance_clock", {"hours": 25})
        r = sb.act("student", "chat", {"message": "request an allowance for RENT-2026-11B"})
        self.assertEqual(r.code, "ALLOWANCE_REQUESTED")
        self.assertIn("BENEFICIARY_CHANGE", self.codes(sb, r.request_id))
        self.assertNotIn("APPROVAL_MISMATCH", self.codes(sb, r.request_id))
        self.assertEqual(reqs(sb)[r.request_id]["risk"]["level"], "high")
        sb.act("operator", "advance_clock", {"hours": 24 * 8})                 # more than a week later
        r2 = reqs(sb)
        if r.request_id in r2 and r2[r.request_id]["status"] == "pending":
            self.assertNotIn("BENEFICIARY_CHANGE", self.codes(sb, r.request_id))

    def test_editing_the_bill_after_the_request_shows_an_approval_mismatch(self):
        sb = make_sandbox()
        r = sb.act("student", "chat", {"message": "pay invoice INV-0003"})
        self.assertNotIn("APPROVAL_MISMATCH", self.codes(sb, r.request_id))
        sb.agent.book.invoices["INV-0003"]["amount"] = "25800.00"
        risk = reqs(sb)[r.request_id]["risk"]
        mm = next(x for x in risk["reasons"] if x["code"] == "APPROVAL_MISMATCH")
        self.assertIn("25,800.00", mm["why"])
        self.assertEqual(risk["level"], "high")
        sb.agent.book.invoices["INV-0003"]["amount"] = "22800.00"
        sb.agent.book.invoices["INV-0003"]["account_number"] = "6222020299999999999"
        mm = next(x for x in reqs(sb)[r.request_id]["risk"]["reasons"] if x["code"] == "APPROVAL_MISMATCH")
        self.assertIn("not the payee's saved account", mm["why"])

    def test_a_mismatch_makes_the_safe_word_necessary(self):
        sb = make_sandbox()
        sb.act("family", "set_safe_word", {"word": "blue lantern"})
        r = sb.act("student", "chat", {"message": "request an allowance for RENT-2026-11"})
        c = sb.act("student", "submit_account_change", {"invoice_id": "RENT-2026-11B"})
        sb.act("family", "decide", {"request_id": c.request_id, "approve": True, "phone_verified": True,
                                    "safe_word": "blue lantern"})
        self.assertEqual(sb.act("family", "decide", {"request_id": r.request_id, "approve": True}).code,
                         "SAFE_WORD_REQUIRED")

    def test_decided_requests_keep_their_stored_risk(self):
        sb = make_sandbox()
        r = sb.act("student", "chat", {"message": "pay invoice INV-0003"})
        sb.act("family", "decide", {"request_id": r.request_id, "approve": False})
        sb.agent.book.invoices["INV-0003"]["amount"] = "1.00"
        self.assertNotIn("APPROVAL_MISMATCH", self.codes(sb, r.request_id))


if __name__ == "__main__":
    unittest.main()
