#!/usr/bin/env python3
"""Collect and sort public posts and comments about paying fees from abroad (run this on YOUR computer).

Why it is a separate tool: StudyBridge's own code never touches the network. This script is only for the problem
research (docs/PROBLEM_RESEARCH.md), and it needs internet access that the build workspace does not have.

What it does
  1. Gathers public text from three places, each through the route that place allows:
       reddit   public search JSON (no key; slow, polite, may be refused with 429 or 403 -- then wait or use --input)
       youtube  YouTube Data API v3 (needs your own free key in YOUTUBE_API_KEY; comments of the top videos)
       x        X API v2 recent search (needs a bearer token in X_BEARER_TOKEN, paid tiers only), or --x-file
                with posts you copied by hand. X pages themselves are not scraped (its terms forbid it).
  2. Removes duplicates and drops user names (only text, source, date and a link are kept).
  3. Sorts every item into themes with plain keyword rules (listed in THEMES; open it and read it).
  4. Writes three files into --out:  items.csv (raw, for your own check),  summary.json,  summary.md (counts per
     theme and source, plus a few short excerpts per theme).

Nothing is invented: every number in summary.md is a count of items in items.csv, and every excerpt is cut from an
item in items.csv. Keyword sorting is crude (it will mislabel some items): say so on the slide, and read a sample.

Usage (Python 3.10+, standard library only)
  py tools/opinion_collect.py --out research_out --reddit --youtube --x
  py tools/opinion_collect.py --out research_out --input my_posts.csv      # sort posts you saved yourself
CSV for --input / --x-file: columns  source,text  (and optionally  url,date).
"""
import argparse
import csv
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

USER_AGENT = "StudyBridge-research/1.0 (student project; contact: team Crossing Borders)"

QUERIES = [
    "international student tuition payment scam",
    "fake invoice university bank details changed international student",
    "paying tuition from Bangladesh student file dollar rate",
    "send money to student abroad fees transfer problem",
    "tuition discount scam stolen card student",
    "fake police call Chinese students scam",
    "education agent consultancy fraud Bangladesh",
]

# Theme -> words or phrases that put an item in it. An item can be in several themes. Lower-case; matched as text.
THEMES = {
    "fake_invoice_or_changed_bank_details": [
        "fake invoice", "changed bank", "new bank details", "updated bank details", "different account",
        "wrong account", "bank details changed", "payment instructions", "spoofed email", "fake email", "phishing",
    ],
    "discount_or_third_party_payer": [
        "discount", "cheaper rate", "better exchange rate", "pay your tuition for you", "stolen card",
        "stolen credit card", "5%", "reimburse", "third party", "payment agent",
    ],
    "impersonation_and_pressure": [
        "pretend", "posing as", "fake police", "embassy", "deport", "arrest", "money laundering", "urgent",
        "pay today", "last chance", "threat", "kidnap", "voice clon", "deepfake",
    ],
    "agent_or_consultancy_fraud": [
        "consultancy", "consultant", "education agent", "agent took", "visa promised", "refund", "cheated",
        "fake admission", "fake offer", "scholarship scam",
    ],
    "forex_and_bank_access": [
        "student file", "dollar rate", "dollar crisis", "forex", "fdr", "bank refused", "bank won't", "bank wont",
        "not opening", "letter of acceptance", "rfcd", "lc rate", "bangladesh bank", "swift",
    ],
    "cost_and_exchange_rate": [
        "hidden fee", "transfer fee", "exchange rate", "markup", "mark-up", "wise", "remitly", "western union",
        "charges", "too expensive", "cheapest way", "best way to send",
    ],
    "informal_channels": ["hundi", "hawala", "black market", "informal", "cash handed", "meet in person"],
    "family_worry_and_trust": [
        "my parents", "my mother", "my father", "family sold", "sold land", "loan for", "worried", "anxious",
        "scared", "stress", "can't trust", "cant trust", "who to trust",
    ],
    "ai_and_automation_risk": [
        "prompt injection", "chatbot", "ai assistant", "ai agent", "hallucinat", "trust ai", "llm",
        "jailbreak", "ai scam", "voice cloning",
    ],
}


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def item_id(source: str, text: str) -> str:
    return hashlib.sha256((source + "|" + norm(text).lower()).encode("utf-8")).hexdigest()[:12]


def classify(text: str):
    """The themes whose words appear in the text, in the order THEMES lists them. Empty list: no theme."""
    low = norm(text).lower()
    return [name for name, words in THEMES.items() if any(w in low for w in words)]


def add_item(items: dict, source: str, text: str, url: str = "", date: str = ""):
    text = norm(text)
    if len(text) < 25 or text in ("[deleted]", "[removed]"):
        return False
    key = item_id(source, text)
    if key in items:
        return False
    items[key] = {"id": key, "source": source, "text": text, "url": url, "date": date}
    return True


# ---------------------------------------------------------------- collectors (network; each takes a fetch function)

def fetch_json(url: str, headers: dict = None, timeout: int = 30):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def collect_reddit(items: dict, fetch=fetch_json, queries=QUERIES, per_query=25, comments_per_post=40, pause=2.0):
    n = 0
    for q in queries:
        url = "https://www.reddit.com/search.json?" + urllib.parse.urlencode(
            {"q": q, "limit": per_query, "sort": "relevance", "t": "all"})
        try:
            data = fetch(url)
        except (urllib.error.URLError, ValueError) as e:
            print(f"reddit: skipped '{q}' ({e})", file=sys.stderr)
            time.sleep(pause)
            continue
        for child in data.get("data", {}).get("children", []):
            post = child.get("data", {})
            link = "https://www.reddit.com" + post.get("permalink", "")
            n += add_item(items, "reddit", post.get("title", "") + ". " + post.get("selftext", ""), link)
            time.sleep(pause)
            try:
                tree = fetch(link.rstrip("/") + ".json?limit=%d" % comments_per_post)
            except (urllib.error.URLError, ValueError):
                continue
            for c in _reddit_comments(tree):
                n += add_item(items, "reddit", c.get("body", ""), link)
        time.sleep(pause)
    return n


def _reddit_comments(tree):
    out = []
    stack = list(tree[1:2]) if isinstance(tree, list) else []
    while stack:
        node = stack.pop()
        data = node.get("data", {}) if isinstance(node, dict) else {}
        for child in data.get("children", []):
            d = child.get("data", {})
            if child.get("kind") == "t1":
                out.append(d)
                replies = d.get("replies")
                if isinstance(replies, dict):
                    stack.append(replies)
    return out


def collect_youtube(items: dict, key: str, fetch=fetch_json, queries=QUERIES, videos=5, comments=100, pause=0.5):
    n = 0
    base = "https://www.googleapis.com/youtube/v3/"
    for q in queries:
        try:
            found = fetch(base + "search?" + urllib.parse.urlencode(
                {"part": "snippet", "type": "video", "maxResults": videos, "q": q, "key": key}))
        except (urllib.error.URLError, ValueError) as e:
            print(f"youtube: skipped '{q}' ({e})", file=sys.stderr)
            continue
        for v in found.get("items", []):
            vid = v.get("id", {}).get("videoId")
            if not vid:
                continue
            link = "https://www.youtube.com/watch?v=" + vid
            n += add_item(items, "youtube", v.get("snippet", {}).get("title", "") + ". " +
                          v.get("snippet", {}).get("description", ""), link)
            try:
                cm = fetch(base + "commentThreads?" + urllib.parse.urlencode(
                    {"part": "snippet", "videoId": vid, "maxResults": min(comments, 100),
                     "textFormat": "plainText", "order": "relevance", "key": key}))
            except (urllib.error.URLError, ValueError):
                continue  # comments off for this video
            for t in cm.get("items", []):
                s = t.get("snippet", {}).get("topLevelComment", {}).get("snippet", {})
                n += add_item(items, "youtube", s.get("textDisplay", ""), link, s.get("publishedAt", ""))
            time.sleep(pause)
    return n


def collect_x(items: dict, bearer: str, fetch=fetch_json, queries=QUERIES, per_query=50):
    n = 0
    for q in queries:
        url = "https://api.twitter.com/2/tweets/search/recent?" + urllib.parse.urlencode(
            {"query": q + " -is:retweet lang:en", "max_results": max(10, min(per_query, 100)),
             "tweet.fields": "created_at"})
        try:
            data = fetch(url, {"Authorization": "Bearer " + bearer})
        except (urllib.error.URLError, ValueError) as e:
            print(f"x: skipped '{q}' ({e})", file=sys.stderr)
            continue
        for t in data.get("data", []):
            n += add_item(items, "x", t.get("text", ""), "https://x.com/i/status/" + str(t.get("id", "")),
                          t.get("created_at", ""))
    return n


def load_csv(items: dict, path: str, default_source: str = "manual"):
    n = 0
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            n += add_item(items, (row.get("source") or default_source).strip().lower() or default_source,
                          row.get("text", ""), row.get("url", ""), row.get("date", ""))
    return n


# ---------------------------------------------------------------- summary

def summarise(items: dict, excerpts_per_theme: int = 3, excerpt_chars: int = 200):
    rows = list(items.values())
    by_theme = defaultdict(list)
    per_source = Counter(r["source"] for r in rows)
    matrix = defaultdict(Counter)
    unsorted = 0
    for r in rows:
        r["themes"] = classify(r["text"])
        if not r["themes"]:
            unsorted += 1
        for t in r["themes"]:
            by_theme[t].append(r)
            matrix[t][r["source"]] += 1
    themes = []
    for name in THEMES:
        got = by_theme.get(name, [])
        # shortest-first among longer-than-60-char items, so excerpts are readable and not whole essays
        sample = sorted((g for g in got if len(g["text"]) >= 60), key=lambda g: len(g["text"]))[:excerpts_per_theme]
        themes.append({
            "theme": name, "items": len(got), "share": round(100 * len(got) / len(rows), 1) if rows else 0.0,
            "by_source": dict(matrix[name]),
            "excerpts": [{"text": s["text"][:excerpt_chars] + ("..." if len(s["text"]) > excerpt_chars else ""),
                          "source": s["source"], "url": s["url"]} for s in sample],
        })
    themes.sort(key=lambda t: -t["items"])
    return {"total_items": len(rows), "per_source": dict(per_source), "unsorted": unsorted, "themes": themes,
            "method": "keyword rules in THEMES (tools/opinion_collect.py); an item can be in several themes; "
                      "counts are of collected items, not of people or of all discussion online"}


def write_outputs(items: dict, out_dir: str):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    summary = summarise(items)
    with open(out / "items.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "source", "date", "url", "themes", "text"])
        for r in items.values():
            w.writerow([r["id"], r["source"], r["date"], r["url"], ";".join(r.get("themes", [])), r["text"]])
    (out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    lines = ["# Public discussion: what people say about paying fees from abroad", "",
             f"Collected items: {summary['total_items']} ({', '.join(f'{k}: {v}' for k, v in summary['per_source'].items()) or 'none'}). "
             f"Not matching any theme: {summary['unsorted']}.", "",
             "Method: " + summary["method"] + ".", "", "| Theme | Items | Share | Where |", "|---|---|---|---|"]
    for t in summary["themes"]:
        where = ", ".join(f"{k} {v}" for k, v in t["by_source"].items()) or "-"
        lines.append(f"| {t['theme'].replace('_', ' ')} | {t['items']} | {t['share']}% | {where} |")
    lines.append("")
    for t in summary["themes"]:
        if t["excerpts"]:
            lines.append(f"## {t['theme'].replace('_', ' ')}")
            for e in t["excerpts"]:
                lines.append(f"- \"{e['text']}\" ({e['source']}{', ' + e['url'] if e['url'] else ''})")
            lines.append("")
    (out / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="research_out")
    ap.add_argument("--reddit", action="store_true")
    ap.add_argument("--youtube", action="store_true")
    ap.add_argument("--x", action="store_true", help="X API v2 (needs X_BEARER_TOKEN)")
    ap.add_argument("--x-file", help="CSV of X posts you saved by hand (columns: text, url, date)")
    ap.add_argument("--input", help="CSV of posts to sort (columns: source, text, optional url, date)")
    args = ap.parse_args(argv)
    items = {}
    if args.input:
        print("input:", load_csv(items, args.input))
    if args.x_file:
        print("x-file:", load_csv(items, args.x_file, "x"))
    if args.reddit:
        print("reddit:", collect_reddit(items))
    if args.youtube:
        key = os.environ.get("YOUTUBE_API_KEY")
        print("youtube:", collect_youtube(items, key) if key else "skipped (set YOUTUBE_API_KEY)")
    if args.x:
        tok = os.environ.get("X_BEARER_TOKEN")
        print("x:", collect_x(items, tok) if tok else "skipped (set X_BEARER_TOKEN)")
    if not items:
        print("Nothing collected. Use --input FILE, or --reddit / --youtube / --x with the keys described above.")
        return 1
    summary = write_outputs(items, args.out)
    print(f"{summary['total_items']} items written to {args.out}/ (items.csv, summary.json, summary.md)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
