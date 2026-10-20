"""v0.6: receipts, the monthly summary, the payment record and the family's tuition reserve."""
import json
import unittest
from decimal import Decimal as D

from studybridge import state
from tests.test_payments import make_sandbox


def pay_tuition(sb):
    r = sb.act("student", "chat", {"message": "pay invoice INV-0003"})
    sb.act("family", "decide", {"request_id": r.request_id, "approve": True})
    a = sb.act("student", "acknowledge", {"request_id": r.request_id})
    return sb.act("student", "confirm", {"id": a.pending_action["id"]})


class TestReceipts(unittest.TestCase):
    def test_each_payment_gets_a_receipt_with_the_bill_route_and_approval(self):
        sb = make_sandbox()
        self.assertEqual(pay_tuition(sb).code, "EXECUTED")
        e = sb.snapshot()["paid"][0]
        self.assertEqual((e["invoice_id"], e["category"], e["on_time"]), ("INV-0003", "University", True))
        for part in ("SANDBOX RECEIPT", "INV-0003", "CNY 22,800.00", "Your AD bank (student file)",
                     "Family approval REQ-", "****3445"):
            self.assertIn(part, e["receipt"])
        self.assertNotIn("6222020200112233445", e["receipt"])                    # account numbers stay masked

    def test_a_canteen_payment_says_it_used_the_daily_limit(self):
        sb = make_sandbox()
        r = sb.act("student", "chat", {"message": "pay 38 CNY at the canteen"})
        sb.act("student", "confirm", {"id": r.pending_action["id"]})
        e = sb.snapshot()["paid"][0]
        self.assertEqual((e["category"], e["approved_by"]), ("Food", "Inside today's family daily limit"))
        self.assertIsNone(e["on_time"])

    def test_receipts_and_the_reserve_survive_a_restart(self):
        sb = make_sandbox()
        pay_tuition(sb)
        sb.act("family", "pot_add", {"bdt": "1000"})
        sb2 = make_sandbox()
        state.load(sb2, json.loads(json.dumps(state.dump(sb))))
        self.assertEqual(sb2.snapshot()["paid"][0]["invoice_id"], "INV-0003")
        self.assertEqual(D(sb2.snapshot()["pot"]["bdt"]), D("1000"))


class TestMonthlySummary(unittest.TestCase):
    def test_last_month_comes_from_the_history_and_tips_skip_fixed_bills(self):
        s = make_sandbox().snapshot()["summary"]
        self.assertEqual((s["month"], s["last_month"]), ("2026-10", "2026-09"))
        rows = {r["category"]: D(r["last_cny"]) for r in s["rows"]}
        self.assertEqual((rows["Rent"], rows["Food"]), (D("1800.00"), D("1160.00")))
        self.assertIn("Food was the biggest part", s["tips"][0])
        self.assertFalse(any("tuition" in t.lower() for t in s["tips"]))   # saving for tuition is the family's tip now

    def test_the_familys_taka_figures_are_what_left_the_wallet(self):
        sb = make_sandbox()
        pay_tuition(sb)
        uni = next(r for r in sb.snapshot()["summary"]["rows"] if r["category"] == "University")
        self.assertEqual((D(uni["this_cny"]), D(uni["this_bdt"])), (D("22800.00"), D("447680.19")))   # not 433,200

    def test_this_month_counts_sandbox_payments(self):
        sb = make_sandbox()
        r = sb.act("student", "chat", {"message": "pay 38 CNY at the canteen"})
        sb.act("student", "confirm", {"id": r.pending_action["id"]})
        rows = {r["category"]: D(r["this_cny"]) for r in sb.snapshot()["summary"]["rows"]}
        self.assertEqual(rows["Food"], D("38.00"))


class TestPaymentRecord(unittest.TestCase):
    def test_record_lists_rent_and_tuition_and_is_not_a_credit_score(self):
        sb = make_sandbox()
        pay_tuition(sb)
        rec = sb.snapshot()["record"]
        self.assertEqual((rec["count"], rec["on_time"], rec["with_due"]), (3, 1, 1))
        self.assertIn("not a credit score", rec["text"])
        self.assertIn("September dorm rent", rec["text"])


class TestTuitionPot(unittest.TestCase):
    def test_everyday_spending_cannot_use_the_reserve_but_tuition_can(self):
        sb = make_sandbox()
        self.assertEqual(sb.act("family", "pot_add", {"bdt": "519000"}).code, "SETTING_CHANGED")
        r = sb.act("student", "chat", {"message": "pay 300 CNY at the canteen"})   # about BDT 5,700; BDT 1,000 free
        self.assertEqual(r.code, "INSUFFICIENT_BALANCE")
        self.assertIn("tuition reserve", r.text)
        self.assertEqual(pay_tuition(sb).code, "EXECUTED")                          # tuition uses the reserve first
        self.assertEqual(D(sb.snapshot()["pot"]["bdt"]), D("519000") - D("447680.19"))

    def test_reserve_added_after_a_payment_was_prepared_is_rechecked(self):
        sb = make_sandbox()
        r = sb.act("student", "chat", {"message": "pay 38 CNY at the canteen"})
        sb.act("family", "pot_add", {"bdt": "520000"})
        self.assertEqual(sb.act("student", "confirm", {"id": r.pending_action["id"]}).code, "INSUFFICIENT_BALANCE")

    def test_only_the_family_puts_money_in_or_takes_it_out(self):
        sb = make_sandbox()
        self.assertEqual(sb.act("student", "pot_add", {"bdt": "5000"}).code, "ACTOR_NOT_PERMITTED")
        sb.act("family", "pot_add", {"bdt": "5000"})
        self.assertEqual(sb.act("student", "pot_release", {"bdt": "5000"}).code, "ACTOR_NOT_PERMITTED")
        self.assertEqual(sb.act("family", "pot_release", {"bdt": "6000"}).code, "INVALID_CHOICE")
        self.assertEqual(sb.act("family", "pot_release", {"bdt": "5000"}).code, "SETTING_CHANGED")

    def test_bad_amounts_are_refused(self):
        sb = make_sandbox()
        for bad in ("0", "-5", "12.5", "abc", "999999999"):
            self.assertTrue(sb.act("family", "pot_add", {"bdt": bad}).blocked, bad)

    def test_reserve_shows_cover_monthly_need_and_exchange_rate_risk(self):
        sb = make_sandbox()
        sb.act("family", "pot_add", {"bdt": "100000"})
        p = sb.snapshot()["pot"]
        self.assertEqual((p["target"]["id"], p["target"]["estimate"]), ("INV-0003", False))
        self.assertEqual(D(p["target"]["need_bdt"]), D("447680.19"))           # the student-file cost, fee included
        self.assertEqual(D(p["fx_2pct_cny"]), D("105.26"))                     # 2% of CNY 5,263.16
        self.assertEqual(D(p["target"]["per_month_bdt"]), D("347680.19"))      # due within a month: all of it now

    def test_after_paying_the_target_is_next_years_bill_estimated(self):
        sb = make_sandbox()
        pay_tuition(sb)
        t = sb.snapshot()["pot"]["target"]
        self.assertEqual((t["estimate"], t["due"], t["amount"]), (True, "2027-11-15", "22800.00"))
        self.assertEqual(t["months"], 13)
        self.assertEqual(D(t["per_month_bdt"]), (D(t["need_bdt"]) / 13).quantize(D("0.01")))


class TestFamilyPin(unittest.TestCase):
    def setUp(self):
        self.sb = make_sandbox()
        self.r = self.sb.act("student", "chat", {"message": "pay invoice INV-0003"})
        self.assertEqual(self.sb.act("family", "set_pin", {"pin": "4826"}).code, "SETTING_CHANGED")
        self.sb.act("family", "lock", {})

    def test_a_locked_family_screen_cannot_approve(self):
        r = self.sb.act("family", "decide", {"request_id": self.r.request_id, "approve": True})
        self.assertEqual(r.code, "FAMILY_LOCKED")
        self.assertEqual(self.sb.agent.book.requests[self.r.request_id]["status"], "pending")
        self.assertEqual(self.sb.act("family", "set_limit", {"cny": 5000}).code, "FAMILY_LOCKED")

    def test_unlock_with_the_pin_then_it_relocks_after_ten_minutes(self):
        self.assertEqual(self.sb.act("family", "unlock", {"pin": "4826"}).code, "SETTING_CHANGED")
        self.assertEqual(self.sb.act("family", "set_limit", {"cny": 600}).code, "SETTING_CHANGED")
        self.sb.agent.clock.advance(hours=0.2)
        self.assertEqual(self.sb.act("family", "set_limit", {"cny": 700}).code, "FAMILY_LOCKED")

    def test_wrong_pins_lock_it_and_nothing_stores_the_pin(self):
        for _ in range(4):
            self.assertEqual(self.sb.act("family", "unlock", {"pin": "1111"}).code, "PIN_WRONG")
        self.assertEqual(self.sb.act("family", "unlock", {"pin": "1111"}).code, "PIN_LOCKED")
        self.assertEqual(self.sb.act("family", "unlock", {"pin": "4826"}).code, "PIN_LOCKED")
        self.assertNotIn("4826", json.dumps(state.dump(self.sb)))
        self.assertNotIn("4826", json.dumps(self.sb.snapshot()))

    def test_changing_or_removing_needs_the_current_pin_and_weak_pins_are_refused(self):
        self.sb.act("family", "unlock", {"pin": "4826"})
        self.assertEqual(self.sb.act("family", "set_pin", {"pin": "", "current": "0000"}).code, "PIN_WRONG")
        for weak in ("12", "7777", "12ab"):
            self.assertEqual(self.sb.act("family", "set_pin", {"pin": weak, "current": "4826"}).code,
                             "INVALID_CHOICE", weak)
        self.assertEqual(self.sb.act("family", "set_pin", {"pin": "", "current": "4826"}).code, "SETTING_CHANGED")
        self.assertFalse(self.sb.snapshot()["family_pin"]["set"])

    def test_the_student_cannot_unlock_or_set_it(self):
        self.assertEqual(self.sb.act("student", "unlock", {"pin": "4826"}).code, "ACTOR_NOT_PERMITTED")
        self.assertEqual(self.sb.act("student", "set_pin", {"pin": "1234"}).code, "ACTOR_NOT_PERMITTED")


class TestUniversityCheck(unittest.TestCase):
    def items(self, sb):
        return {i["title"]: i for i in sb.snapshot()["unicheck"]["items"]}

    def test_facts_from_stored_bills_and_no_prediction(self):
        it = self.items(make_sandbox())
        self.assertEqual(it["Tuition change from last year"]["level"], "ok")
        self.assertIn("INV-0011", it["5 tuition bills ask for another account"]["detail"])
        self.assertEqual(it["No official payment page on file"]["level"], "info")
        self.assertFalse(any("bankrupt" in i["detail"].lower() for i in it.values()))

    def test_a_fee_rise_above_ten_percent_is_flagged(self):
        sb = make_sandbox()
        sb.agent.book.invoices["INV-0003"]["amount"] = D("25500.00")
        item = self.items(sb)["Tuition change from last year"]
        self.assertEqual(item["level"], "warn")
        self.assertIn("+11.8%", item["detail"])

    def test_a_university_with_an_official_page_is_named(self):
        sb = make_sandbox()
        sb.agent.wallet.owner["university"] = "Shenzhen University"
        self.assertIn("lxs.szu.edu.cn".split(".", 1)[1], self.items(sb)["Official payment page on file"]["detail"])


if __name__ == "__main__":
    unittest.main()
