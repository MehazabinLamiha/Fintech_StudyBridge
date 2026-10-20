"""Checking a bill against the university's own website (official.py). No network: saved copies and fake fetchers."""
import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest import mock

from studybridge import official
from tests.test_payments import CountingLLM, make_sandbox

TODAY = date(2026, 10, 19)
REAL = ("Shenzhen University tuition invoice. Beneficiary: SHENZHEN UNIVERSITY. A/C No.: 7484 6706 4612. "
        "SWIFT BKCHCNBJ45A. Receipt to cieoffice@szu.edu.cn")
FAKE = ("URGENT: our bank account has changed. Pay to A/C 6222 0202 0099 8877 661, SWIFT ICBKCNBJSZN. "
        "Reply to szu.finance.office@gmail.com")
SZU = official.UNIVERSITIES["szu"]


def saved(uni="szu"):
    return official.load_pages(uni, online=False)


class TestOfficialSite(unittest.TestCase):
    def test_only_the_universitys_own_edu_cn_address(self):
        self.assertTrue(official.is_official("https://lxs.szu.edu.cn/info/1.htm", SZU))
        self.assertTrue(official.is_official("https://szu.edu.cn/", SZU))
        for bad in ("https://szu.edu.cn.example.com/", "https://fakeszu.edu.cn/", "ftp://szu.edu.cn/",
                    "https://xn--szu-9oa.edu.cn/", "https://szu-edu.cn/"):
            self.assertFalse(official.is_official(bad, SZU), bad)
        self.assertFalse(official.is_official("https://www.example.com/", {"domain": "example.com"}))   # not .edu.cn

    def test_every_listed_page_is_official_and_has_a_saved_copy(self):
        for uni_id, uni in official.UNIVERSITIES.items():
            pages = saved(uni_id)
            self.assertEqual(len(pages), len(uni["pages"]), uni_id)
            for p in pages:
                self.assertTrue(official.is_official(p["url"], uni))
                self.assertTrue(official.read_bill(p["text"])["accounts"], f"{uni_id}: no account on {p['url']}")

    def test_fetch_refuses_other_sites_and_off_site_redirects(self):
        with self.assertRaises(ValueError):
            official.fetch("https://evil.example.com/pay", SZU)

        class Moved:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def geturl(self): return "https://evil.example.com/pay"
            def read(self, n): return b"A/C 123456789012"
        with mock.patch("urllib.request.urlopen", return_value=Moved()), self.assertRaises(ValueError):
            official.fetch("https://lxs.szu.edu.cn/info/1003/2849.htm", SZU)


class TestReadAndCheck(unittest.TestCase):
    def test_reading_a_bill(self):
        b = official.read_bill(REAL)
        self.assertEqual(b["accounts"], ["748467064612"])         # groups joined
        self.assertEqual(b["swift"], ["BKCHCNBJ45A"])
        self.assertEqual(b["emails"], ["cieoffice@szu.edu.cn"])
        self.assertEqual(official.read_bill("学费请转账到cieoffice@szu.edu.cn")["emails"], ["cieoffice@szu.edu.cn"])

    def test_real_bill_matches_and_fake_does_not(self):
        real = official.check(official.read_bill(REAL), "szu", saved(), TODAY)
        self.assertEqual(real["verdict"], "MATCHES_OFFICIAL")
        self.assertTrue(real["accounts"][0]["found"] and real["swift"][0]["found"])
        self.assertIn("cieoffice@szu.edu.cn", real["official_emails"])
        fake = official.check(official.read_bill(FAKE), "szu", saved(), TODAY)
        self.assertEqual(fake["verdict"], "NOT_ON_OFFICIAL")
        self.assertEqual(fake["foreign_emails"], ["szu.finance.office@gmail.com"])

    def test_right_account_wrong_swift_is_not_a_match(self):
        r = official.check(official.read_bill("A/C 748467064612 SWIFT ICBKCNBJSZN"), "szu", saved(), TODAY)
        self.assertEqual(r["verdict"], "NOT_ON_OFFICIAL")

    def test_another_universitys_account_is_not_a_match(self):
        r = official.check(official.read_bill("A/C 51001837108051514771 SWIFT PCBCCNBJSCX"), "szu", saved(), TODAY)
        self.assertEqual(r["verdict"], "NOT_ON_OFFICIAL")

    def test_nothing_to_check(self):
        self.assertEqual(official.check(official.read_bill("pay now"), "szu", saved(), TODAY)["verdict"],
                         "NO_ACCOUNT_IN_BILL")
        self.assertEqual(official.check(official.read_bill(REAL), "szu", [], TODAY)["verdict"], "NO_OFFICIAL_PAGE")

    def test_page_date_is_the_latest_date_not_after_today(self):
        self.assertEqual(official.latest_date("2023年2月7日 … 2022-02-15 … 2099-01-01", TODAY), "2023-02-07")


class TestLoadPages(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        patcher = mock.patch.object(official, "LIVE", self.tmp)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_live_page_is_used_and_kept(self):
        pages = official.load_pages("swufe", fetcher=lambda url, uni: "A/C 99998888777766 SWIFT ABCDCNBJ123",
                                    now=datetime(2026, 10, 19, 10, 0))
        self.assertEqual(pages[0]["source"], "live")
        self.assertTrue((self.tmp / "swufe-1.json").exists())

    def test_falls_back_to_the_saved_copy_when_offline(self):
        def down(url, uni):
            raise OSError("no network")
        pages = official.load_pages("szu", fetcher=down)
        self.assertEqual([p["source"] for p in pages], ["saved", "saved"])
        self.assertEqual(pages[0]["error"], "OSError")


class TestAction(unittest.TestCase):
    def test_result_is_masked_and_the_bill_is_not_logged(self):
        sb = make_sandbox()
        r = sb.act("student", "verify_bill", {"university": "szu", "text": REAL})
        self.assertEqual(r.data["verdict"], "MATCHES_OFFICIAL")
        out = json.dumps(r.to_dict(), ensure_ascii=False)
        self.assertNotIn("748467064612", out)
        self.assertIn("****4612", out)
        log = Path(sb.audit.path).read_text(encoding="utf-8")
        self.assertIn("official_check", log)
        self.assertNotIn("748467064612", log)
        self.assertNotIn("Beneficiary", log)                       # the pasted text is never written

    def test_who_may_check(self):
        sb = make_sandbox()
        self.assertEqual(sb.act("family", "verify_bill", {"university": "szu", "text": FAKE}).data["verdict"],
                         "NOT_ON_OFFICIAL")
        self.assertEqual(sb.act("operator", "verify_bill", {"university": "szu", "text": FAKE}).code,
                         "ACTOR_NOT_PERMITTED")
        self.assertEqual(sb.act("student", "verify_bill", {"university": "mit", "text": FAKE}).code, "INVALID_CHOICE")
        self.assertEqual(sb.act("student", "verify_bill", {"university": "szu", "text": " "}).code, "INVALID_CHOICE")

    def test_qwen_summary_loses_any_number_it_types(self):
        llm = CountingLLM(text="Pay by bank transfer to the account on the official page. Use account 748467064612. "
                               "E-mail the receipt to the college afterwards.")
        sb = make_sandbox(llm=llm)
        r = sb.act("student", "verify_bill", {"university": "szu", "text": FAKE})
        self.assertEqual(r.data["verdict"], "NOT_ON_OFFICIAL")       # code decided; Qwen only summarised
        self.assertTrue(r.data["qwen"]["used"])
        self.assertNotIn("748467064612", r.data["qwen"]["text"])
        self.assertIn("bank transfer", r.data["qwen"]["text"])
        self.assertNotIn("748467064612", llm.calls[-1])            # the page excerpt sent to Qwen is masked too
        self.assertNotIn("6222", llm.calls[-1])                    # and the pasted bill is never sent


if __name__ == "__main__":
    unittest.main()
