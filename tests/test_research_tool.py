"""The opinion collector (tools/opinion_collect.py) is run by hand, but its sorting and summary are tested here with
made-up sample posts and fake network functions, so no test touches the network."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

_PATH = Path(__file__).resolve().parent.parent / "tools" / "opinion_collect.py"
_spec = importlib.util.spec_from_file_location("opinion_collect", _PATH)
oc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(oc)

SAMPLES = [
    ("reddit", "I almost paid a fake invoice, the email said our bank details changed and the account was different."),
    ("reddit", "My bank is not opening a student file and the dollar rate they quote is far above the market."),
    ("youtube", "Someone offered me a discount to pay my tuition with a stolen card, the payment was reversed later."),
    ("x", "My parents sold land to pay the agent and the consultancy took the money, no refund at all."),
    ("x", "What a lovely sunny day for a walk in the park with friends today."),
]


class TestOpinionCollect(unittest.TestCase):
    def test_classify(self):
        self.assertIn("fake_invoice_or_changed_bank_details", oc.classify(SAMPLES[0][1]))
        self.assertIn("forex_and_bank_access", oc.classify(SAMPLES[1][1]))
        self.assertIn("discount_or_third_party_payer", oc.classify(SAMPLES[2][1]))
        got = oc.classify(SAMPLES[3][1])
        self.assertIn("agent_or_consultancy_fraud", got)
        self.assertIn("family_worry_and_trust", got)
        self.assertEqual(oc.classify(SAMPLES[4][1]), [])

    def test_duplicates_and_noise_dropped(self):
        items = {}
        self.assertTrue(oc.add_item(items, "reddit", SAMPLES[0][1]))
        self.assertFalse(oc.add_item(items, "reddit", "  " + SAMPLES[0][1].upper() + " "))   # same text, other case
        self.assertFalse(oc.add_item(items, "reddit", "[deleted]"))
        self.assertFalse(oc.add_item(items, "reddit", "too short"))
        self.assertEqual(len(items), 1)

    def test_summary_counts_match_items(self):
        items = {}
        for s, t in SAMPLES:
            oc.add_item(items, s, t)
        summary = oc.summarise(items)
        self.assertEqual(summary["total_items"], 5)
        self.assertEqual(summary["unsorted"], 1)
        self.assertEqual(sum(summary["per_source"].values()), 5)
        for t in summary["themes"]:
            self.assertEqual(sum(t["by_source"].values()), t["items"])
            for e in t["excerpts"]:                      # every excerpt is cut from a collected item
                self.assertTrue(any(r["text"].startswith(e["text"].rstrip(".")) for r in items.values()))

    def test_outputs_and_no_usernames(self):
        items = {}
        for s, t in SAMPLES:
            oc.add_item(items, s, t, "https://example.test/1")
        with tempfile.TemporaryDirectory() as d:
            oc.write_outputs(items, d)
            for name in ("items.csv", "summary.json", "summary.md"):
                self.assertTrue((Path(d) / name).exists())
            header = (Path(d) / "items.csv").read_text(encoding="utf-8").splitlines()[0]
            self.assertEqual(header, "id,source,date,url,themes,text")        # no author column
            self.assertIn("fake invoice or changed bank details", (Path(d) / "summary.md").read_text(encoding="utf-8"))

    def test_csv_input(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "in.csv"
            p.write_text("source,text,url\nreddit,\"%s\",http://x.test/a\n" % SAMPLES[1][1], encoding="utf-8")
            items = {}
            self.assertEqual(oc.load_csv(items, str(p)), 1)
            self.assertEqual(next(iter(items.values()))["source"], "reddit")

    def test_collectors_with_fake_network(self):
        def fake(url, headers=None):
            if "reddit.com/search.json" in url:
                return {"data": {"children": [{"data": {"title": "Student scam", "selftext": SAMPLES[0][1],
                                                         "permalink": "/r/x/comments/abc/t/"}}]}}
            if "reddit.com/r/x/comments" in url:
                return [{}, {"data": {"children": [{"kind": "t1", "data": {"body": SAMPLES[1][1], "replies": {
                    "data": {"children": [{"kind": "t1", "data": {"body": SAMPLES[2][1]}}]}}}}]}}]
            if "youtube/v3/search" in url:
                return {"items": [{"id": {"videoId": "vid1"}, "snippet": {"title": "Scam warning video", "description": ""}}]}
            if "youtube/v3/commentThreads" in url:
                return {"items": [{"snippet": {"topLevelComment": {"snippet": {"textDisplay": SAMPLES[3][1]}}}}]}
            if "tweets/search/recent" in url:
                assert headers and headers["Authorization"] == "Bearer tok"
                return {"data": [{"id": 1, "text": SAMPLES[0][1] + " (x)", "created_at": "2026-01-01"}]}
            raise AssertionError(url)

        items = {}
        self.assertEqual(oc.collect_reddit(items, fake, queries=["q"], pause=0), 3)   # the post and two comments (one a reply)
        self.assertEqual(oc.collect_youtube(items, "key", fake, queries=["q"], pause=0), 1)
        self.assertEqual(oc.collect_x(items, "tok", fake, queries=["q"]), 1)
        self.assertEqual({r["source"] for r in items.values()}, {"reddit", "youtube", "x"})


if __name__ == "__main__":
    unittest.main()
