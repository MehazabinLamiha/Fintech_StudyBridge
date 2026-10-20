"""Invoice X-ray: view data that shows WHY a bill looks wrong.

Everything here is derived from what the code already knows (the saved payee, the stored invoice and the
guard's own pattern lists). It never decides anything: Gate 1 decides exactly as before. Full account
numbers never leave the server: only the positions where two numbers differ, and the last four digits that
mask_account() already shows.
"""
import difflib
import re

from .security.audit import mask_account, mask_text
from .security.guard import flag_spans

_TOKEN = re.compile(r"[^\s()]+")
_EDGE = ".,;:"


def _merge(segs: list) -> list:
    out = []
    for text, mark in segs:
        if not text and mark != "missing":
            continue
        if out and out[-1]["m"] == mark and mark != "missing":
            out[-1]["t"] += text
        else:
            out.append({"t": text, "m": mark})
    return out


def issuer_segments(issuer: str, saved_name: str) -> list:
    """The issuer line split into plain and marked parts: 'typo' (a letter that differs or is extra),
    'missing' (t holds the letter the saved name has and the bill lacks) and 'extra' (a whole word the saved
    name does not have)."""
    saved_words = {w.strip(_EDGE).lower() for w in _TOKEN.findall(saved_name) if w.strip(_EDGE)}
    segs, pos = [], 0
    for m in _TOKEN.finditer(issuer):
        segs.append((issuer[pos:m.start()], None))
        pos = m.end()
        tok = m.group()
        core = tok.strip(_EDGE)
        lead = tok[:len(tok) - len(tok.lstrip(_EDGE))]
        trail = tok[len(lead) + len(core):]
        low = core.lower()
        if not core or low in saved_words:
            segs.append((tok, None))
            continue
        near = difflib.get_close_matches(low, sorted(saved_words), n=1, cutoff=0.8)
        if not near:
            segs.append((tok, "extra"))
            continue
        segs.append((lead, None))
        for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, low, near[0]).get_opcodes():
            if op == "equal":
                segs.append((core[i1:i2], None))
            elif op in ("replace", "delete"):
                segs.append((core[i1:i2], "typo"))
            else:                                   # insert: the saved name has letters this bill lacks
                segs.append((near[0][j1:j2], "missing"))
        segs.append((trail, None))
    segs.append((issuer[pos:], None))
    return _merge(segs)


def account_diff(bill_account, saved_account) -> dict:
    """Where the account on the bill differs from the saved one. Positions only, never the numbers."""
    a, b = str(bill_account or ""), str(saved_account or "")
    if not a:
        return {"same": True, "kind": "none", "length": 0, "positions": [], "last4": ""}
    if a == b:
        return {"same": True, "kind": "same", "length": len(a), "positions": [], "last4": a[-4:]}
    if len(a) == len(b):
        positions = [i for i in range(len(a)) if a[i] != b[i]]
        kind = "digits"
    else:
        positions, kind = list(range(len(a))), "different"
    return {"same": False, "kind": kind, "length": len(a), "positions": positions,
            "last4": a[-4:], "saved_length": len(b), "saved_last4": b[-4:]}


def memo_segments(memo: str) -> list:
    """The memo (digit runs masked) split into plain, 'pressure' and 'injection' parts."""
    text = mask_text(memo or "")
    segs, pos = [], 0
    for a, b, kind in flag_spans(text):
        segs.append((text[pos:a], None))
        segs.append((text[a:b], kind))
        pos = b
    segs.append((text[pos:], None))
    return _merge(segs)


def build(inv: dict, payee: dict, owner_name, gate1_code) -> dict:
    """The X-ray of one stored invoice. owner_name: the saved payee that owns the bill's account, if any."""
    issuer = inv.get("issuer")
    issuer_segs = issuer_segments(issuer, payee["name"]) if issuer else []
    diff = account_diff(inv.get("account_number"), payee.get("account_number"))
    memo = memo_segments(inv.get("memo", ""))
    flagged_memo = any(s["m"] for s in memo)
    marked_issuer = any(s["m"] for s in issuer_segs)
    return {
        "suspicious": bool((not diff["same"]) or marked_issuer or flagged_memo),
        "issuer": issuer_segs,
        "saved_name": payee["name"],
        "account": diff,
        "saved_account": mask_account(payee["account_number"]) if payee.get("account_number") else None,
        "belongs_to": owner_name,
        "payee_type": payee["type"],
        "memo": memo,
        "pressure": any(s["m"] == "pressure" for s in memo),
        "injection": any(s["m"] == "injection" for s in memo),
        "gate1": gate1_code,
    }
