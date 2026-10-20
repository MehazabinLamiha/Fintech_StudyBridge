"""Output and input guards.

numeric grounding guard
    Every number (and ISO date) the LLM writes must match a number in the
    tool results or the user's own message, within a rounding tolerance.
    A sentence with an ungrounded number is cut in code; the model is not
    asked to fix itself, because small models often repeat the same error.

untrusted-text handling
    Transaction memos, beneficiary names and similar fields come from third
    parties. They are scanned for instruction-like text and are never used
    to choose a tool or fill an argument.
"""
import re
import unicodedata
from decimal import Decimal, InvalidOperation

_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_NUM = re.compile(r"(?<![A-Za-z])-?\d[\d,]*(?:\.\d+)?")
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
SMALL_INT_OK = 10          # bare integers up to this are counts/list markers (never with a currency or label)
REL_TOL = Decimal("0.005")
ABS_TOL = Decimal("0.01")

_INJECTION = re.compile(
    r"ignore (all|any|previous|prior|the above)|disregard .*(instruction|rule|approval|limit|check)|"
    r"you are now|developer mode|\bjailbreak\b|\bdan mode\b|pretend (you are|to be|you're)|"
    r"transfer (all|everything)|send (all|everything)|"
    r"new instruction|act as|override|ignore (your|the|these|my) (rules|instructions|limits)|"
    r"forget (your|the|all|any|previous|prior) (rules|instructions|limits|training)|"
    r"without (the )?(family )?(approval|confirmation)|skip (the )?(family|approval|confirmation|check)|"
    r"(do not|don'?t|never) (tell|inform|ask|notify|alert|involve) (the |my |your )?(family|parents?|mother|father|guardian)|"
    r"without (telling|asking|informing|notifying) (the |my |your )?(family|parents?|mother|father|guardian)|"
    r"(decode|base64|rot13)\b.{0,30}\b(and )?(follow|execute|run|obey|do)|"
    r"\bbypass\b|pre-?approved|note to (the )?assistant|"
    # Banglish and Bangla versions of the same tricks
    r"(approval|onumodon|confirm|check)\s+(chara|charai|lagbe na|ni(y|)e)|"
    r"(family|poribar|poribarke|abba|amma|baba|ma)\s*(ke)?\s*(na|bina)\s*(jan(i|ie)y|bol(e|a))|"
    r"(shob|sob|sokol|puro)\s+(taka|balance)\s+(pathao|pathiye|transfer)|"
    r"(niyom|rules?|instruction|nirdesh)\w*\s+(ignore|bhule|vule|na mane)|"
    r"(ager|purber|aager)\s+(shob\s+)?(niyom|nirdesh|instruction)|bhule\s+jao|vule\s+jao|"
    r"অনুমোদন\s*ছাড়া|পরিবারকে\s*না\s*জানিয়ে|সব\s*টাকা\s*পাঠা|নিয়ম\s*(ভুলে|উপেক্ষা)|আগের\s*(সব\s*)?(নির্দেশ|নিয়ম)",
    re.IGNORECASE,
)

# "Mum already approved it": approval can only be given on the family's own screen, so for a money request this
# claim is treated like the instruction wording above. It is not applied to questions and other information requests.
_CLAIMED_APPROVAL = re.compile(
    r"\b(family|mother|father|parents?|mom|mum|dad|guardian|bank|admin|manager|university|officer)( \w+){0,2} "
    r"(already )?(approved|said (it is|it's) (ok|okay|fine)|agreed|allowed|authori[sz]ed|cleared)( it| this| that)?"
    r"( on the phone| by phone| verbally)?|\bpre-?cleared\b",
    re.IGNORECASE,
)

_ZERO_WIDTH = re.compile("[\u200b-\u200f\u202a-\u202e\u2060\ufeff\u00ad]")
_SPACED = re.compile(r"\b(?:[a-z][ .\-_*]){3,}[a-z]\b")
_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s", "!": "i"})
_LEET_WORD = re.compile(r"(?<![\d-])\b(?=[a-z0-9@$!]*[a-z])(?=[a-z0-9@$!]*[01345 7@$!])[a-z0-9@$!]{4,}\b")


def deobfuscate(text: str) -> str:
    """Lower-cased text with the usual disguises undone, for detection only (never shown, never acted on):
    full-width and look-alike letters (NFKC), zero-width characters, spaced-out letters ("i g n o r e") and
    leetspeak inside words ("ign0re"). Digits that stand alone (invoice ids, amounts) are left alone."""
    t = _ZERO_WIDTH.sub("", unicodedata.normalize("NFKC", text or "")).lower()
    t = _SPACED.sub(lambda m: re.sub(r"[ .\-_*]", "", m.group()), t)

    def leet(m):
        w = m.group()
        out = w.translate(_LEET)
        return out if out.isalpha() and sum(c.isalpha() for c in w) >= len(w) // 2 else w
    return _LEET_WORD.sub(leet, t)


# Pressure wording typical of consultancy scams. It never changes a decision;
# it is shown to the student and the family as a warning.
_PRESSURE = re.compile(
    r"pay (today|now|immediately)|lose (your|the) (seat|place|admission|offer)|\burgent\b|final (notice|warning)|"
    r"last chance|act now|within \d+ hours|immediately|or (your|the) (admission|visa|offer) (will be|is) cancel",
    re.IGNORECASE,
)


def looks_like_injection(text: str) -> bool:
    """True for instruction-override, approval-skipping, secrecy-from-the-family and "send everything" wording,
    also when it is disguised (spaced letters, leetspeak, full-width letters, zero-width characters)."""
    return bool(text) and bool(_INJECTION.search(text) or _INJECTION.search(deobfuscate(text)))


def claims_approval(text: str) -> bool:
    """A claim that someone has already approved the payment (only meaningful for a money request)."""
    return bool(text) and bool(_CLAIMED_APPROVAL.search(text) or _CLAIMED_APPROVAL.search(deobfuscate(text)))


def flag_spans(text: str) -> list:
    """(start, end, kind) for every pressure phrase and injection phrase in text, in order, not overlapping.
    View data for the invoice X-ray: it marks what the detectors already found and decides nothing."""
    spans = [(m.start(), m.end(), "pressure") for m in _PRESSURE.finditer(text or "")]
    spans += [(m.start(), m.end(), "injection") for m in _INJECTION.finditer(text or "")]
    spans += [(m.start(), m.end(), "injection") for m in _CLAIMED_APPROVAL.finditer(text or "")]
    spans.sort()
    out, last = [], 0
    for a, b, kind in spans:
        if a >= last:
            out.append((a, b, kind))
            last = b
    return out


def pressure_signals(text: str) -> list:
    return sorted({m.group(0).lower() for m in _PRESSURE.finditer(text or "")})


def numbers_in(text: str) -> list:
    text = _DATE.sub(" ", text)
    out = []
    for tok in _NUM.findall(text):
        tok = tok.replace(",", "").rstrip(".")
        try:
            out.append(Decimal(tok))
        except InvalidOperation:
            continue
    return out


def dates_in(text: str) -> set:
    return set(_DATE.findall(text))


def _grounded(x: Decimal, pool: list) -> bool:
    ax = abs(x)
    if ax == ax.to_integral_value() and ax <= SMALL_INT_OK:
        return True
    for s in pool:
        s = abs(s)
        if abs(ax - s) <= max(ABS_TOL, REL_TOL * s):
            return True
    return False


_NUMTXT = r"(-?\d[\d,]*(?:\.\d+)?)"
_CODES = r"(BDT|CNY|USD|THB|EUR|RMB|YUAN|TAKA)"
_PAIR_BEFORE = re.compile(r"\b" + _CODES + r"\s*" + _NUMTXT, re.IGNORECASE)
_PAIR_AFTER = re.compile(_NUMTXT + r"\s*" + _CODES + r"\b", re.IGNORECASE)
_PCT = re.compile(_NUMTXT + r"\s*%")
_DOLLAR = re.compile(r"\$\s*" + _NUMTXT)
_PCT_KEY = re.compile(r'"[^"]*pct[^"]*"\s*:\s*"?' + _NUMTXT)
_CODE_NORM = {"RMB": "CNY", "YUAN": "CNY", "TAKA": "BDT"}

# Claims a finance assistant must never make, whatever the numbers say.
ALWAYS_FORBIDDEN = [r"\bguarantee", r"\brisk[- ]free\b", r"\bno risk\b"]


def _dec(tok: str) -> Decimal:
    return Decimal(tok.replace(",", "").rstrip("."))


def _pairs(text: str) -> list:
    text = _DATE.sub(" ", text)
    out = [(_CODE_NORM.get(c.upper(), c.upper()), _dec(n)) for c, n in _PAIR_BEFORE.findall(text)]
    out += [(_CODE_NORM.get(c.upper(), c.upper()), _dec(n)) for n, c in _PAIR_AFTER.findall(text)]
    out += [("USD", _dec(n)) for n in _DOLLAR.findall(text)]
    return out


def _close(a: Decimal, b: Decimal) -> bool:
    a, b = abs(a), abs(b)
    return abs(a - b) <= max(ABS_TOL, REL_TOL * b)


# Words that say what a number is. A number written next to one of these must sit next to the
# same word somewhere in the sources ("limit CNY 500" cannot become "balance CNY 500").
_LABELS = {
    "balance": r"balances?|holds?",
    "limit": r"limits?",
    "remaining": r"left|remaining",
    "fee": r"fees?",
    "cap": r"caps?",
}
_LABEL_RE = re.compile(r"(?i)\b(" + "|".join(f"(?P<{k}>{v})" for k, v in _LABELS.items()) + r")\b|_(?P<k2>"
                       + "|".join(_LABELS) + r")\b")
_IDS = re.compile(r"\b[A-Z]{2,}-[A-Z0-9-]+\b")
_LABEL_WINDOW = 20


def _labelled(text: str) -> list:
    """(label, number) pairs: each label word with the nearest number within a short window."""
    text = _IDS.sub(lambda m: " " * len(m.group()), _DATE.sub(lambda m: " " * len(m.group()), text))
    nums = [(m.start(), m.end(), m.group()) for m in _NUM.finditer(text)]
    out = []
    for m in _LABEL_RE.finditer(text):
        label = m.lastgroup if m.lastgroup != "k2" else m.group("k2").lower()
        if label not in _LABELS:
            label = next(k for k in _LABELS if m.group(k))
        best = None
        for s, e, tok in nums:
            gap = s - m.end() if s >= m.end() else m.start() - e
            between = text[m.end():s] if s >= m.end() else text[e:m.start()]
            # Never pair across a JSON field or a line: '"limit.", "detail": "CNY 280' is two facts.
            if '"' in between or "\n" in between:
                continue
            if 0 <= gap <= _LABEL_WINDOW and (best is None or gap < best[0]):
                best = (gap, tok)
        if best:
            try:
                out.append((label, _dec(best[1])))
            except InvalidOperation:
                continue
    return out


def enforce_grounding(text: str, sources: list, forbidden: list = ()) -> tuple:
    """Return (clean_text, removed_sentences).

    A sentence is cut when it contains
      - a number or ISO date that is not in the sources,
      - a percentage whose value is not a percentage in the sources,
      - an amount labelled with a different currency than in the sources,
      - a number next to a label (balance, limit, left, fee, cap) that the sources only
        attach to other numbers,
      - a forbidden claim (e.g. 'guaranteed', a status word the outcome does not support, or a
        term the tool must not use).
    Known limit: a number with no label nearby, attached to the wrong thing in plain words, can
    still pass.
    """
    pool, pool_dates, pool_pairs, pool_pct, pool_labels = [], set(), [], [], []
    for s in sources:
        pool.extend(numbers_in(s))
        pool_dates |= dates_in(s)
        pool_pairs += _pairs(s)
        pool_pct += [_dec(n) for n in _PCT.findall(s)] + [_dec(n) for n in _PCT_KEY.findall(s)]
        pool_labels += _labelled(s)
    banned = [re.compile(p, re.IGNORECASE) for p in list(ALWAYS_FORBIDDEN) + list(forbidden)]

    kept, removed = [], []
    for sent in _SENTENCE.split(text):
        if not sent.strip():
            continue
        bad = [n for n in numbers_in(sent) if not _grounded(n, pool)]
        bad += [d for d in dates_in(sent) if d not in pool_dates]
        bad += [n for n in map(_dec, _PCT.findall(sent)) if not any(_close(n, p) for p in pool_pct)]
        for ccy, n in _pairs(sent):
            known = {pc for pc, pn in pool_pairs if _close(n, pn)}
            if known and ccy not in known:
                bad.append(f"{n} {ccy}")
            elif not any(_close(n, pn) for pn in pool):      # small amounts get no free pass with a currency
                bad.append(f"{n} {ccy}")
        for label, n in _labelled(sent):
            known = [pn for pl, pn in pool_labels if pl == label]
            if known and not any(_close(n, pn) for pn in known):
                bad.append(f"{label} {n}")
        bad += [b.pattern for b in banned if b.search(sent)]
        (removed if bad else kept).append(sent.strip())
    return " ".join(kept), removed


def amount_grounded_in(amount, message: str) -> bool:
    """True if `amount` literally appears in the user's message."""
    if amount is None:
        return True
    try:
        a = Decimal(str(amount))
    except InvalidOperation:
        return False
    return any(abs(a - n) <= ABS_TOL for n in numbers_in(message))


def wrap_untrusted(text: str, limit: int = 200) -> str:
    clean = "".join(ch for ch in str(text) if ch.isprintable())[:limit]
    return f"<untrusted_data>{clean}</untrusted_data>"
