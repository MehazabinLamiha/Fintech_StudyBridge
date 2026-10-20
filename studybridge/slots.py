"""Fill-in-the-blank numbers for Qwen's explanation.

Qwen gets the facts as JSON plus one placeholder per number in them, and must write numbers only as
{placeholder}. Code then fills each placeholder with the value from the facts, so every number in the
explanation comes from code and sits where Qwen put its name. A sentence is removed when it names a
placeholder that does not exist, or types a digit itself. Digits inside a token copied exactly from the
facts (an invoice id, a date, a masked account such as ****3446) are allowed.
Known limits: Qwen could still put a real placeholder next to the wrong word ({food_bdt} after "rent"), and a
claim with no number in it ("rent and food are each about half") is not checked by this step.
"""
import re
from decimal import Decimal

_NUMERIC = re.compile(r"-?\d+(?:\.\d+)?")
_SLOT = re.compile(r"\{([a-z0-9_]+)\}")
_TOKEN_WITH_DIGIT = re.compile(r"[^\s,;:()\"'{}]*\d[^\s,;:()\"'{}]*")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_LABEL_KEYS = ("category", "name", "provider", "payee", "id")   # names a list item better than its position


def _slug(s) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(s).lower()).strip("_")


def _show(v, name: str = "") -> str:
    """The value as the facts show it: thousands separators, the same number of decimals; percentages get %."""
    text = str(v)
    places = len(text.split(".")[1]) if "." in text else 0
    return f"{Decimal(text):,.{places}f}" + ("%" if name.endswith(("pct", "percent")) else "")


def collect(view) -> tuple:
    """(placeholders: name -> shown value, tokens with digits that may be copied as they are) for a JSON-like view."""
    slots, verbatim = {}, set()

    def walk(o, path):
        if isinstance(o, dict):
            for k, v in o.items():
                walk(v, path + [k])
        elif isinstance(o, list):
            for i, v in enumerate(o):
                label = next((v[k] for k in _LABEL_KEYS if isinstance(v, dict) and isinstance(v.get(k), str)), i)
                walk(v, path + [label])
        elif isinstance(o, bool) or o is None:
            return
        elif isinstance(o, (int, float, Decimal)) or (isinstance(o, str) and _NUMERIC.fullmatch(o)):
            name = base = _slug("_".join(map(str, path))) or "value"
            n = 2
            while name in slots:
                name, n = f"{base}_{n}", n + 1
            slots[name] = _show(o, name)
        elif isinstance(o, str):
            verbatim.update(_TOKEN_WITH_DIGIT.findall(o))

    walk(view, [])
    return slots, verbatim


def fill(text: str, slots: dict, verbatim: set) -> tuple:
    """(text with placeholders filled, removed sentences)."""
    kept, removed = [], []
    for sentence in filter(None, _SENTENCE.split((text or "").strip())):
        if any(name not in slots for name in _SLOT.findall(sentence)):
            removed.append(sentence)
            continue
        rest = _SLOT.sub(" ", sentence)
        for token in sorted(verbatim, key=len, reverse=True):
            rest = rest.replace(token, " ")
        if re.search(r"\d", rest):                      # a digit Qwen typed itself
            removed.append(sentence)
            continue
        kept.append(_SLOT.sub(lambda m: slots[m.group(1)], sentence).replace("%%", "%"))   # "{x_pct}%" -> one %
    return " ".join(kept), removed
