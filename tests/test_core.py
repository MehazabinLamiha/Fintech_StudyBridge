import unittest
from datetime import date
from decimal import Decimal as D

from studybridge import credit, fx, remittance, tuition
from studybridge.money import mid_rate, norm_ccy


class TestMoney(unittest.TestCase):
    def test_aliases(self):
        self.assertEqual(norm_ccy("rmb"), "CNY")
        self.assertEqual(norm_ccy("Taka"), "BDT")
        with self.assertRaises(ValueError):
            norm_ccy("XYZ")

    def test_cross_rate(self):
        self.assertAlmostEqual(float(mid_rate("BDT", "CNY") * mid_rate("CNY", "BDT")), 1.0, places=12)


class TestFx(unittest.TestCase):
    def test_spread_applied(self):
        qt = fx.quote(10000, "BDT", "CNY")
        self.assertLess(qt["applied_rate"], qt["mid_rate"])
        self.assertEqual(qt["you_get"], D("524.21"))

    def test_rejects_non_positive(self):
        with self.assertRaises(ValueError):
            fx.quote(0, "BDT", "CNY")


class TestRemittance(unittest.TestCase):
    def test_ranked_by_recipient_amount(self):
        res = remittance.compare(50000, "BDT", "CNY")
        eligible = [o["recipient_gets"] for o in res["options"] if o["eligible"]]
        self.assertEqual(eligible, sorted(eligible, reverse=True))
        self.assertEqual(res["best"]["provider_id"], "digital_a")

    def test_deadline_filters_slow_provider(self):
        res = remittance.compare(50000, "BDT", "CNY", deadline_days=1)
        swift = next(o for o in res["options"] if o["provider_id"] == "bank_swift")
        self.assertFalse(swift["eligible"])

    def test_tuition_purpose_keeps_only_the_student_file_route(self):
        res = remittance.compare(400000, "BDT", "CNY", purpose="tuition")
        self.assertEqual([o["provider_id"] for o in res["options"] if o["eligible"]], ["bank_swift"])
        others = [o for o in res["options"] if o["provider_id"] != "bank_swift"]
        self.assertTrue(all(any("not allowed for tuition" in r for r in o["reasons"]) for o in others))
        self.assertEqual(remittance.compare(400000, "BDT", "CNY")["best"]["provider_id"], "digital_a")  # living money

    def test_corridor_and_max_limits(self):
        res = remittance.compare(20000, "CNY", "BDT")
        wallet_c = next(o for o in res["options"] if o["provider_id"] == "wallet_c")
        self.assertIn("corridor CNY->BDT not supported", wallet_c["reasons"])
        self.assertIn("above provider maximum", wallet_c["reasons"])
        with self.assertRaises(ValueError):                 # only BDT, CNY and USD
            remittance.compare(200000, "BDT", "EUR")

    def test_inverse_is_exact(self):
        p = remittance.provider_by_id("digital_a")
        need = remittance.source_needed(p, 5700, "BDT", "CNY")
        got = remittance.evaluate(p, need, "BDT", "CNY")["recipient_gets"]
        self.assertEqual(got, D("5700.00"))


class TestTuition(unittest.TestCase):
    BAL = {"BDT": D("520000"), "CNY": D("3200")}
    TODAY = date(2026, 10, 13)

    @staticmethod
    def inv(due, amount="22800", iid="INV-0003"):
        return {"id": iid, "purpose": "Tuition 2026-27 (full year)", "amount": amount, "currency": "CNY", "due": due}

    def test_one_transfer_for_the_full_invoice(self):
        res = tuition.plan([self.inv("2026-11-15")], self.TODAY, self.BAL)
        self.assertEqual(res["status"], "ON_TRACK")
        self.assertEqual(len(res["invoices"]), 1)
        row = res["invoices"][0]
        self.assertEqual(row["amount"], D("22800.00"))
        self.assertEqual(row["provider_id"], "bank_swift")       # tuition goes only through the student file
        self.assertEqual(row["send_amount"], D("447680.19"))     # under the BDT 2,500,000 tuition limit
        self.assertEqual(row["send_by"], "2026-11-09")           # due - 3 safety days - 3 delivery days

    def test_funding_gap(self):
        res = tuition.plan([self.inv("2026-11-15")], self.TODAY, {"BDT": D("100000")})
        self.assertEqual(res["status"], "FUNDING_GAP")
        self.assertGreater(res["funding_gap"], 0)

    def test_urgent_and_overdue(self):
        self.assertEqual(tuition.plan([self.inv("2026-10-18")], self.TODAY, self.BAL)["status"], "URGENT")
        late = tuition.plan([self.inv("2026-10-14")], self.TODAY, self.BAL)     # the bank needs 3 days
        self.assertEqual(late["status"], "NO_PROVIDER")
        self.assertIn("extension", late["invoices"][0]["advice"])
        self.assertEqual(tuition.plan([self.inv("2026-10-01")], self.TODAY, self.BAL)["status"], "OVERDUE")

    def test_nothing_due(self):
        self.assertEqual(tuition.plan([], self.TODAY, self.BAL)["status"], "NOTHING_DUE")


class TestCredit(unittest.TestCase):
    def test_thin_file(self):
        res = credit.assess({"months_in_country": 1})
        self.assertEqual(res["stage"], "THIN_FILE")
        self.assertTrue(any("bank account" in a for a in res["actions"]))

    def test_high_utilisation_flagged(self):
        res = credit.assess({"months_in_country": 24, "has_local_bank_account": True, "has_credit_card": True,
                             "card_limit": 1000, "card_balance": 600, "on_time_payments_12m": 12})
        self.assertEqual(res["utilisation_pct"], D("60.00"))
        self.assertTrue(any("below 30%" in a for a in res["actions"]))

    def test_established(self):
        res = credit.assess({"months_in_country": 24, "has_local_bank_account": True, "has_credit_card": True,
                             "has_phone_contract": True, "card_limit": 1000, "card_balance": 50,
                             "on_time_payments_12m": 12})
        self.assertEqual(res["stage"], "ESTABLISHED")


if __name__ == "__main__":
    unittest.main()
