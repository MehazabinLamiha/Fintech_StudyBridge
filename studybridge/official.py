"""Check a real bill against the university's own website.

The scam in a tuition payment is nearly always a changed bank account. Real Chinese universities publish their
tuition account on their official site, which sits on the university's own `.edu.cn` address (only Chinese education
institutions can register under .edu.cn). So the check is:

    1. read the account numbers, SWIFT codes and e-mail addresses in the bill the student pasted (rules, not Qwen);
    2. read the university's official payment page, live or from a saved copy;
    3. code says whether each account and SWIFT code in the bill appears on that page, and shows where.

Only pages from the list below are ever fetched (never a URL taken from a bill or typed by a user), only over the
university's own .edu.cn address, and a redirect that leaves it is refused. A match is strong evidence, not proof: the
page can be out of date, so the result always names the page's latest date and the official address to confirm with.
Qwen, when it is on, only writes a plain-words summary of the official page; it decides nothing.
"""
import hashlib
import html
import json
import re
import urllib.request
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

from . import PROJECT_ROOT

SAVED = PROJECT_ROOT / "data" / "official_pages"      # saved copies, committed with their fetch date
LIVE = PROJECT_ROOT / "var" / "official_pages"        # copies fetched while the app runs (not committed)
MAX_BYTES = 2_000_000
MAX_BILL_CHARS = 4000

# Checked by the team: each page is on the university's own .edu.cn site and lists its tuition account.
UNIVERSITIES = {
    "szu": {"name": "Shenzhen University", "domain": "szu.edu.cn",
            "pages": ["https://lxs.szu.edu.cn/info/1003/2849.htm", "https://lxs.szu.edu.cn/info/1003/2522.htm"]},
    "swufe": {"name": "Southwestern University of Finance and Economics", "domain": "swufe.edu.cn",
              "pages": ["https://international.swufe.edu.cn/EN/Admissions/Payment.htm"]},
    "sjtu": {"name": "Shanghai Jiao Tong University", "domain": "sjtu.edu.cn",
             "pages": ["https://gk.sjtu.edu.cn/Data/View/613"]},
    "shsmu": {"name": "Shanghai Jiao Tong University School of Medicine", "domain": "shsmu.edu.cn",
              "pages": ["https://www.shsmu.edu.cn/iso/info/1022/1106.htm"]},
    "suda": {"name": "Soochow University (Medical College)", "domain": "suda.edu.cn",
             "pages": ["https://isso.medical.suda.edu.cn/c9/20250901/i13543.shtml"]},
}

_DIGITS = re.compile(r"\d(?:[\d \-]{6,40})\d")                      # an account may be written in groups
_SWIFT = re.compile(r"\b[A-Z]{4}CN[A-Z0-9]{2}(?:[A-Z0-9]{3})?\b")   # Chinese banks only (country code CN)
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)")   # ASCII only, so Chinese text is not glued on
_DATE = re.compile(r"(20\d\d)\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})")


def is_official(url: str, uni: dict) -> bool:
    """True only for http(s) on the university's own domain, and only if that domain is under .edu.cn."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    domain = uni["domain"]
    return (parts.scheme in ("https", "http") and domain.endswith(".edu.cn") and host.isascii()
            and (host == domain or host.endswith("." + domain)))


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        self.skip += tag in ("script", "style")

    def handle_endtag(self, tag):
        self.skip -= tag in ("script", "style")
        if tag in ("p", "div", "br", "tr", "li", "h1", "h2", "h3", "td"):
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def page_text(raw: bytes) -> str:
    m = re.search(rb'charset=["\']?([\w-]+)', raw[:4000])
    enc = m.group(1).decode() if m else "utf-8"
    try:
        doc = raw.decode(enc, "replace")
    except LookupError:
        doc = raw.decode("utf-8", "replace")
    p = _Text()
    p.feed(doc)
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n", html.unescape("".join(p.out)))).strip()


def fetch(url: str, uni: dict, timeout: float = 8) -> str:
    """The text of one official page. Raises ValueError for anything that is not the university's own site."""
    if not is_official(url, uni):
        raise ValueError(f"{url} is not on {uni['domain']}")
    req = urllib.request.Request(url, headers={"User-Agent": "StudyBridge/0.5 (student payment check)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        if not is_official(r.geturl(), uni):
            raise ValueError(f"{url} redirected to {r.geturl()}, which is not on {uni['domain']}")
        raw = r.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError(f"{url} is larger than {MAX_BYTES} bytes")
    return page_text(raw)


def _copy_path(folder: Path, uni_id: str, i: int) -> Path:
    return folder / f"{uni_id}-{i + 1}.json"


def _read_copy(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save_copy(folder: Path, uni_id: str, i: int, url: str, text: str, now: datetime) -> dict:
    rec = {"url": url, "fetched_at": now.isoformat(timespec="minutes"),
           "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "text": text}
    folder.mkdir(parents=True, exist_ok=True)
    _copy_path(folder, uni_id, i).write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    return rec


def load_pages(uni_id: str, online: bool = True, fetcher=fetch, now=None) -> list:
    """Each official page as {url, fetched_at, sha256, text, source}: fetched now when possible, otherwise the most
    recent copy (one fetched while the app ran, then the committed saved copy). A page with no copy is left out."""
    uni = UNIVERSITIES[uni_id]
    now = now or datetime.now()
    pages = []
    for i, url in enumerate(uni["pages"]):
        rec, error = None, None
        if online:
            try:
                rec = {**save_copy(LIVE, uni_id, i, url, fetcher(url, uni), now), "source": "live"}
            except (OSError, ValueError) as exc:
                error = type(exc).__name__
        if rec is None:
            copies = [c for c in (_read_copy(_copy_path(LIVE, uni_id, i)), _read_copy(_copy_path(SAVED, uni_id, i)))
                      if c and c.get("url") == url]
            if copies:
                rec = {**max(copies, key=lambda c: c["fetched_at"]), "source": "saved"}
        if rec:
            pages.append({**rec, "error": error})
    return pages


def norm_numbers(text: str) -> set:
    """Account-like numbers (8 to 34 digits) with spaces and dashes removed."""
    out = set()
    for m in _DIGITS.finditer(text):
        d = re.sub(r"\D", "", m.group(0))
        if 8 <= len(d) <= 34:
            out.add(d)
    return out


def read_bill(text: str) -> dict:
    """What the bill says, read by rules: account numbers, SWIFT codes, e-mail addresses."""
    text = str(text or "")[:MAX_BILL_CHARS]
    return {"accounts": sorted(norm_numbers(text)), "swift": sorted(set(_SWIFT.findall(text.upper()))),
            "emails": sorted({m.group(0).lower() for m in _EMAIL.finditer(text)})}


def _snippet(text: str, needle: str, digits: bool) -> str:
    """About 70 characters either side of the first place the needle appears (digits matched across spaces)."""
    if digits:
        pat = re.compile(r"\D?".join(needle))
        m = pat.search(text)
    else:
        m = re.search(re.escape(needle), text, re.IGNORECASE)
    if not m:
        return ""
    return " ".join(text[max(0, m.start() - 70):m.end() + 70].split())


def latest_date(text: str, today) -> str:
    dates = []
    for y, mo, d in _DATE.findall(text):
        try:
            day = datetime(int(y), int(mo), int(d)).date()
        except ValueError:
            continue
        if day <= today:
            dates.append(day)
    return max(dates).isoformat() if dates else None


def check(bill: dict, uni_id: str, pages: list, today) -> dict:
    """Compare what the bill says with the official pages. Code only."""
    uni = UNIVERSITIES[uni_id]
    page_nums = [(p, norm_numbers(p["text"])) for p in pages]
    page_swift = [(p, set(_SWIFT.findall(p["text"].upper()))) for p in pages]

    def where(found_in):
        return [{"url": p["url"], "snippet": s} for p, s in found_in if s]

    accounts = [{"account": a, "found": where((p, _snippet(p["text"], a, True)) for p, nums in page_nums if a in nums)}
                for a in bill["accounts"]]
    swift = [{"swift": s, "found": where((p, _snippet(p["text"], s, False)) for p, codes in page_swift if s in codes)}
             for s in bill["swift"]]
    official_emails = sorted({m.group(0).lower() for p in pages for m in _EMAIL.finditer(p["text"])
                              if m.group(1).lower() == uni["domain"] or m.group(1).lower().endswith("." + uni["domain"])})
    foreign_emails = [e for e in bill["emails"]
                      if not (e.split("@")[1] == uni["domain"] or e.split("@")[1].endswith("." + uni["domain"]))]
    if not pages:
        verdict = "NO_OFFICIAL_PAGE"
    elif not accounts:
        verdict = "NO_ACCOUNT_IN_BILL"
    elif all(a["found"] for a in accounts) and all(s["found"] for s in swift):
        verdict = "MATCHES_OFFICIAL"
    else:
        verdict = "NOT_ON_OFFICIAL"
    return {"verdict": verdict, "university": uni["name"], "domain": uni["domain"], "accounts": accounts,
            "swift": swift, "official_emails": official_emails, "foreign_emails": foreign_emails,
            "pages": [{"url": p["url"], "source": p["source"], "fetched_at": p["fetched_at"], "sha256": p["sha256"],
                       "latest_date": latest_date(p["text"], today), "error": p.get("error")} for p in pages]}


def mask(text: str) -> str:
    """Account-like numbers shown as ****1234 (the screen never shows a full account number)."""
    return _DIGITS.sub(lambda m: "****" + re.sub(r"\D", "", m.group(0))[-4:]
                       if 8 <= len(re.sub(r"\D", "", m.group(0))) <= 34 else m.group(0), text)


def payment_excerpt(pages: list, limit: int = 2500) -> str:
    """The part of the official pages that is about paying, for Qwen's plain-words summary."""
    keys = re.compile(r"tuition|payment|transfer|remit|account|beneficiary|swift|refund|学费|汇款|账号|帐号|缴费",
                      re.IGNORECASE)
    lines = [ln for p in pages for ln in p["text"].splitlines() if keys.search(ln)]
    return mask("\n".join(lines))[:limit]
