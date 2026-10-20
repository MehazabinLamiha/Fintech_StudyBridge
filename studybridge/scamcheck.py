"""Is this message a scam? Rules only, on text the student pastes.

The check looks for the patterns that public reports describe (see cases.py and docs/PROBLEM_RESEARCH.md): pressure,
a deal that is too good, a stranger offering to pay, fake authority, secrecy, changed bank details, hard-to-trace
payment methods, a refund that needs money sent back, requests for logins or codes, a link, a "family member" on a
new number, and instructions aimed at an AI assistant. It also looks for account numbers and says whether each one
is an account the family saved.

What it does not do, on purpose:
  * It never says a message is safe. "No warning signs found" ends with "check with the university directly".
  * It never sends the pasted text to Qwen or writes it to the audit log. Qwen, when it is on, is given only the
    list of signal names that this code found.
  * It decides nothing about money. A message pasted here cannot start a payment.
"""
import re

from .cases import CASES
from .security.guard import _PRESSURE, claims_approval, deobfuscate

MAX_CHARS = 2000

# kind -> (label, why, severity 1..3, pattern)
_S = {
    "pressure": ("Pressure to act fast", "Scammers rush people so they do not check.", 2, re.compile(
        _PRESSURE.pattern + r"|only (for )?(this|today|tonight|the next) \w+|many students already( did it)?|"
        r"within (24|48|12|2) ?(hours|hrs)|before (midnight|tonight)|do it now|right now|"
        r"don'?t (delay|wait)", re.IGNORECASE)),
    "too_good": ("A deal that is too good", "Real universities do not give discounts through strangers.", 2,
                 re.compile(r"\b\d{1,2} ?% (off|discount|cashback|back|reimburse\w*)|\bdiscount\w*|\bcheaper\b|"
                            r"better (exchange )?rate|\bcashback\b|special (rate|price|offer)|\bfor free\b|"
                            r"reimburse\w*", re.IGNORECASE)),
    "stranger_pays": ("A stranger offers to pay for you", "The usual trick: they pay with a stolen card and the "
                      "payment is reversed later.", 3,
                      re.compile(r"\b(i|we|he|she|they|someone|\w+) (will|can|'ll|offers? to|promis\w+ to) pay "
                                 r"(my|the|your) (university|school|fee|fees|tuition)|"
                                 r"send (him|her|them) .{0,40}\b(and|then|so) (he|she|they)\b|"
                                 r"send (me|us) .{0,40}\b(and|then|so) (i|we) (will|'ll|can)|"
                                 r"pay (the )?(university|tuition|fees?) (for you|on your behalf)|"
                                 r"(my|our) company card|through (me|my office|our office)|"
                                 r"i help students pay", re.IGNORECASE)),
    "authority": ("Pretending to be an authority", "Police, embassies, immigration and universities do not demand "
                  "money by message or phone.", 3,
                  re.compile(r"\b(police|officer|bureau|embassy|consulate|immigration|customs|court|prosecutor|"
                             r"ministry|tax (office|department)|bank security|fraud department)\b|"
                             r"money laundering|\barrest(ed)?\b|deport\w*|visa (will be|is) (cancel|revok)\w*|"
                             r"visa (cancel|revok)\w*|legal action|warrant", re.IGNORECASE)),
    "tariff": ("An unknown fee or tax", "Governments do not charge an 'international student tariff' by wire.", 3,
               re.compile(r"international student (tariff|tax|fee|levy)|student (tariff|levy)|"
                          r"visa (fee|tax) (by|via) (wire|transfer)", re.IGNORECASE)),
    "secrecy": ("Asking you to keep it secret", "Secrecy is how scammers keep family and friends from stopping "
                "the payment.", 3,
                re.compile(r"(do not|don'?t|never) (tell|inform|ask|call|contact|involve|mention)( \w+){0,3} "
                           r"(family|parents?|mum|mom|dad|mother|father|school|university|anyone|anybody|me back)|"
                           r"keep (this|it) (secret|private|between us|quiet)|between us|confidential|"
                           r"(do not|don'?t) call (me )?back", re.IGNORECASE)),
    "changed_bank": ("New bank details", "A changed account is the classic way to redirect a real payment.", 3,
                     re.compile(r"(bank|account|payment) (account |details |instructions )?(has|have|had) changed|"
                                r"(new|updated|changed|different) (bank|account|payment)( account| details| "
                                r"instructions)?|old account (is |was )?(closed|inactive|no longer)|"
                                r"account (is )?(closed|frozen|suspended)|change of (bank|account)", re.IGNORECASE)),
    "unusual_method": ("A hard-to-trace way to pay", "Wire, gift cards, crypto and 'safe accounts' cannot be got "
                       "back.", 3,
                       re.compile(r"\b(gift ?cards?|itunes|steam card|bitcoin|crypto\w*|usdt|tether|western union|"
                                  r"moneygram|money order|cash app|paypal friends)\b|safe account|"
                                  r"(personal|private) (account|wallet|alipay|wechat)|by wire\b|wire transfer",
                                  re.IGNORECASE)),
    "refund_back": ("A refund that needs money sent first", "A real refund never needs you to send money first.", 3,
                    re.compile(r"(overcharged|charged twice|double charged|overpaid|over-paid)|"
                               r"(send|pay|transfer|return)( \w+){0,3} back\b|"
                               r"(unlock|release|claim) (the |your )?refund|refund .{0,30}(first|fee|deposit)",
                               re.IGNORECASE)),
    "credentials": ("Asking for a login or code", "Nobody legitimate needs your password, PIN or one-time code.", 3,
                    re.compile(r"\b(password|passcode|pin ?code|\bpin\b|otp|one[- ]time (code|password)|"
                               r"verification code|security code|net ?id|student portal login|log ?in details|"
                               r"cvv|cvc)\b", re.IGNORECASE)),
    "link": ("A link to follow", "Type the university's address yourself instead of following links in messages.", 2,
             re.compile(r"https?://\S+|\bwww\.\S+|\b(bit\.ly|tinyurl\.com|t\.co|goo\.gl|cutt\.ly|rb\.gy)/\S*",
                        re.IGNORECASE)),
    "family_voice": ("A 'family member' on a new number", "Cloned voices and new numbers are used to get money "
                     "from family fast.", 3,
                     re.compile(r"(it'?s|this is) me\b.{0,60}(new number|friend'?s (phone|number)|phone (broke|is "
                                r"broken|died|stolen|lost))|new number|(lost|broke|broken|stolen) (my )?phone|"
                                r"i('m| am) in (trouble|jail|hospital|danger)|"
                                r"(mum|mom|dad|mother|father)[, ]+(it'?s|this is) me", re.IGNORECASE)),
    "agent_deposit": ("An agent asking for a deposit", "Agents who take money for a visa or place and do not "
                      "deliver are a documented problem.", 2,
                      re.compile(r"\b(agent|consultant|consultancy)\b.{0,60}\b(deposit|advance|guarantee|fee|"
                                 r"payment)\b|\b(deposit|advance|guarantee)\b.{0,60}\b(visa|admission|seat|"
                                 r"place)\b|guaranteed (visa|admission)", re.IGNORECASE)),
}

# Wording aimed at an AI assistant (not the "do not tell your family" kind, which is the secrecy signal above).
_AI_WORDS = re.compile(
    r"ignore (all|any|previous|prior|the above|your|these)|disregard .{0,30}(instruction|rule|check)|"
    r"you are now|developer mode|\bjailbreak\b|pretend (you are|to be|you're)|new instruction|"
    r"note to (the )?assistant|system prompt|as an ai\b|(decode|base64)\b.{0,30}(follow|execute|obey)|"
    r"pre-?approved|skip (the )?(family|approval|confirmation|check)|without (the )?(family )?approval|"
    r"\boverride\b|\bbypass\b", re.IGNORECASE)

# Signals that alone make the verdict "very likely a scam".
STRONG = {"refund_back", "changed_bank", "stranger_pays", "tariff", "unusual_method", "ai_instruction"}

# Account-like digit strings (8 to 24 digits, spaces or dashes allowed inside).
_ACCT = re.compile(r"(?<![\d.])\d(?:[ -]?\d){7,23}(?![\d.])")

# Which public case a message most resembles, by the signals it shows (first match wins).
_CASE_BY_SIGNAL = [("tariff", "student-tariff"), ("refund_back", "refund-back"), ("family_voice", "voice-clone"),
                   ("authority", "police-call"), ("stranger_pays", "discount-stranger"),
                   ("too_good", "discount-stranger"), ("changed_bank", "new-bank-details"),
                   ("agent_deposit", "agent-deposit")]

_NEXT = [
    "Do not pay, reply or click anything yet.",
    "Contact the university's finance office using the phone number or address on its own website, not one from "
    "the message.",
    "Tell your family before any money moves. Scams depend on you keeping quiet.",
    "In StudyBridge, pay only a stored bill: a payment goes only to the account the family saved for that payee.",
]


def _mask(num: str) -> str:
    digits = re.sub(r"\D", "", num)
    return "…" + digits[-4:]


def check(text: str, payees=None) -> dict:
    """The result for one pasted message. `payees` is an iterable of saved payees (dicts with name, account_number,
    verified); the full account numbers stay inside this function, only the last four digits are returned."""
    text = (text or "").strip()[:MAX_CHARS]
    flat = deobfuscate(text)
    signals, spans = [], []
    for kind, (label, why, sev, rx) in _S.items():
        hits = list(rx.finditer(text)) or list(rx.finditer(flat))
        if hits:
            signals.append({"kind": kind, "label": label, "why": why, "severity": sev, "count": len(hits)})
            if rx.search(text):
                spans += [(m.start(), m.end(), kind) for m in hits[:3]]
    if _AI_WORDS.search(text) or _AI_WORDS.search(flat) or claims_approval(text):
        signals.append({"kind": "ai_instruction", "label": "Instructions aimed at an AI assistant",
                        "why": "A message that tells an assistant to skip checks or approvals is an attack; "
                               "StudyBridge treats message text as data and never follows it.", "severity": 3,
                        "count": 1})
        spans += [(m.start(), m.end(), "ai_instruction") for m in _AI_WORDS.finditer(text)][:3]

    saved = {re.sub(r"\D", "", p.get("account_number", "")): p for p in (payees or [])}
    accounts = []
    for m in _ACCT.finditer(text):
        digits = re.sub(r"\D", "", m.group())
        p = saved.get(digits)
        accounts.append({"last4": _mask(digits), "saved": bool(p),
                         "payee": p.get("name") if p else None})
        spans.append((m.start(), m.end(), "account"))
    unknown = [a for a in accounts if not a["saved"]]
    if unknown:
        signals.append({"kind": "unknown_account", "label": "An account that the family has not saved",
                        "why": "StudyBridge pays only accounts the family saved for a payee, so a number in a "
                               "message cannot be a payee.", "severity": 2, "count": len(unknown)})

    score = sum(s["severity"] for s in signals)
    kinds = {s["kind"] for s in signals}
    if "unknown_account" in kinds and kinds & {"pressure", "authority", "changed_bank", "stranger_pays",
                                               "too_good", "refund_back", "tariff", "unusual_method"}:
        score += 2                                   # a payment demand plus an account nobody saved
    if score >= 5 or kinds & STRONG:
        verdict, level = "Very likely a scam", "danger"
    elif score >= 2:
        verdict, level = "Suspicious: check before you do anything", "warn"
    else:
        verdict, level = "No warning signs found in the wording", "ok"

    case = None
    for kind, cid in _CASE_BY_SIGNAL:
        if kind in kinds:
            c = CASES[cid]
            case = {"id": cid, "title": c["title"], "what": c["what"], "source_title": c["source_title"],
                    "source_url": c["source_url"]}
            break

    spans.sort()
    clean, last = [], 0
    for a, b, k in spans:
        if a >= last:
            clean.append({"start": a, "end": b, "kind": k})
            last = b
    signals.sort(key=lambda s: -s["severity"])
    nxt = list(_NEXT) if level != "ok" else [
        "This does not mean the message is safe. A careful scammer can avoid every word looked for here.",
        "Before paying anything, check with the university using contact details from its own website.",
    ]
    return {"verdict": verdict, "level": level, "score": score, "signals": signals, "spans": clean,
            "accounts": accounts, "case": case, "next": nxt, "length": len(text),
            "truncated": len((text or "")) > MAX_CHARS}


def quiz_items() -> list:
    """The quiz messages, without the answers."""
    from .cases import QUIZ
    return [{"id": q["id"], "text": q["text"]} for q in QUIZ]


def quiz_answer(item_id: str, says_scam: bool, payees=None):
    """Grade one answer. Returns None for an unknown id; else whether the student was right, the answer, the case
    it copies and the signals this checker finds in the same text (so the reveal shows what to look for)."""
    from .cases import QUIZ
    q = next((x for x in QUIZ if x["id"] == item_id), None)
    if q is None:
        return None
    res = check(q["text"], payees)
    case = CASES.get(q["case"]) if q["case"] else None
    return {"id": q["id"], "right": bool(says_scam) == q["scam"], "scam": q["scam"],
            "text": q["text"], "signals": res["signals"], "spans": res["spans"],
            "case": ({"title": case["title"], "what": case["what"], "source_title": case["source_title"],
                      "source_url": case["source_url"]} if case else None)}
