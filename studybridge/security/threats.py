"""What an attack on the assistant looks like, for the refusals, the red alert screen and the scam-challenge score.

This is detection and labelling only. The money rules (Gate 1, family approval, limits, student confirms last) do not
depend on it: an attack that none of these patterns recognises still cannot move money, because chat text never
chooses a payee, an account, an actor, a permission or an approval. What these patterns add is an early, clearly
named refusal, before the message reaches Qwen, for the attacks that are written to be read by a language model.

Labels follow the OWASP Top 10 for LLM Applications (2025 edition). Only the categories this code really acts on
are used: LLM01 prompt injection, LLM02 sensitive information disclosure, LLM05 improper output handling,
LLM06 excessive agency, LLM07 system prompt leakage and LLM10 unbounded consumption.
"""
import re

from .guard import claims_approval, deobfuscate, looks_like_injection

OWASP = {
    "LLM01": "Prompt Injection",
    "LLM02": "Sensitive Information Disclosure",
    "LLM05": "Improper Output Handling",
    "LLM06": "Excessive Agency",
    "LLM07": "System Prompt Leakage",
    "LLM10": "Unbounded Consumption",
}

_ASK = (r"(?:show|tell|give|send|print|reveal|share|read|display|list|dump|leak|expose|output|paste|recite|"
        r"what(?:'s| is| are| was| were)|dekhao|bolo|dao|দেখাও|বলো|দাও)")

# LLM07: the assistant's own instructions.
_PROMPT_LEAK = re.compile(
    r"\b(?:system|hidden|initial|original|secret|internal|developer)\s*(?:prompt|instructions?|message|rules|configuration|config)\b|"
    r"\b" + _ASK + r"\b.{0,30}\b(?:your|the)\s+(?:prompt|instructions?|rules|guidelines|configuration|setup|programming)\b|"
    r"\bwhat\s+(?:are|were)\s+your\s+(?:instructions|rules|guidelines)\b|"
    r"\bwhat\s+(?:instructions|rules|guidelines|prompt)\s+(?:were|are|did|do)\s+you\b|"
    r"\brepeat\s+(?:everything|all|the (?:text|words)|your\s+\w+)\s+(?:above|before|so far)\b|"
    r"\b(?:everything|text|words)\s+(?:above|before)\s+(?:this|my)\b|"
    r"\b(?:prompt|instruction|nirdesh|niyom)\w*\s+(?:dekhao|bolo|dao)\b|(?:নির্দেশ|প্রম্পট)\s*(?:দেখাও|বলো)",
    re.IGNORECASE,
)

# LLM02: secrets and personal or internal data.
_SECRET_WORDS = (r"(?:password|passcode|passphrase|\bpin\b|\botp\b|\bcvv\b|\bcvc\b|api[ _-]?key|secret(?: key)?|private key|"
                 r"\btoken\b|credentials?|ssh key|(?:safe|code|secret|magic) ?word|পাসওয়ার্ড|পিন)")
_SECRET_DATA = re.compile(
    r"\b" + _ASK + r"\b.{0,40}" + _SECRET_WORDS + "|" +
    r"\b(?:full|complete|entire|whole|unmasked|real|actual|raw|every)\b.{0,20}\b(?:account|card|bank|iban|swift)\b|"
    r"\b" + _ASK + r"\b.{0,40}\b(?:account|card|bank|iban)\s*(?:number|no\.?|details|digits)\b|"
    r"\b(?:family|parents?|mother|father|mom|mum|dad|guardian|student|owner|dean|staff|officer)(?:'s|s)?\b.{0,15}"
    r"\b(?:phone|mobile|cell|whatsapp|nid|passport|home address|email)\b|"
    r"\b" + _ASK + r"\b.{0,40}(?:\.head\b|\bstate file\b|\bsample_profile\b|profile\.json|\bsource code\b|"
    r"\benvironment variables?\b|\benv vars?\b|\bconfig file\b)",
    re.IGNORECASE,
)

# LLM06: chat text trying to act as someone else, widen a permission or limit, or confirm for the student.
_PRIVILEGE = re.compile(
    r"\b(?:i am|i'm|im|this is|we are|speaking as|acting as|ami)\b.{0,15}\b(?:the |an? |your )?"
    r"(?:admin|administrator|operator|owner|developer|root|superuser|system|support|bank (?:staff|officer|manager)|"
    r"family|parent|mother|father|guardian)\b|"
    r"\b(?:set|change|switch|upgrade|raise|grant|give|enable|unlock|turn on|escalate)\b.{0,30}\b(?:tier|permissions?|"
    r"privileges?|access|role|admin mode|operator mode|transact|developer mode)\b|"
    r"\b(?:sudo|root access)\b|\b(?:log ?in|login) as\b|"
    r"\bswitch to (?:the )?(?:operator|family|admin|student)\b|"
    r"\bconfirm\b.{0,20}\b(?:all|every|pending|payments?|transfers?)\b",
    re.IGNORECASE,
)
# An order to change a limit. A question about limits ("can I raise my limit?") is a normal question and is answered.
_LIMIT_ORDER = re.compile(
    r"\b(?:raise|increase|change|remove|lift|set|double|triple|disable|turn off|waive|bypass)\b.{0,25}\b"
    r"(?:daily |spending |family |my |the |hard )?(?:limit|cap)\b",
    re.IGNORECASE,
)
_QUESTION = re.compile(r"\?\s*$|^\s*(?:how|what|can|could|is|are|does|do|will|would|should)\b", re.IGNORECASE)

# LLM05: markup or template syntax in the message. The page shows message text as plain text only, so this is
# noted, not refused.
_MARKUP = re.compile(
    r"<\s*/?\s*(?:script|img|iframe|svg|object|embed|style|link|a|body|html|form|input)\b|javascript:|"
    r"\bon(?:error|load|click|mouseover|focus)\s*=|\{\{.*?\}\}|\$\{.*?\}",
    re.IGNORECASE,
)

# What each kind of attack is called on the screen and what the code answers.
KINDS = {
    "injection": {"code": "INJECTION_DETECTED", "owasp": "LLM01", "label": "Prompt injection", "level": "danger",
                  "detail": "The message contains instruction-override, approval-skipping, secrecy-from-the-family "
                            "or 'send everything' wording (spaced letters, look-alike characters and leetspeak "
                            "included), so nothing was done with it and Qwen did not see it."},
    "secret": {"code": "SECRET_REQUEST", "owasp": "LLM02", "label": "Sensitive information request", "level": "danger",
               "detail": "The message asks for something the assistant never gives out: passwords or keys, full "
                         "account numbers, phone numbers or internal files."},
    "system_prompt": {"code": "SECRET_REQUEST", "owasp": "LLM07", "label": "System prompt leakage attempt",
                      "level": "danger",
                      "detail": "The message asks the assistant to repeat its own instructions. They are not shared "
                                "in chat; the Glass Box shows exactly what Qwen is sent."},
    "privilege": {"code": "ACTOR_NOT_PERMITTED", "owasp": "LLM06", "label": "Excessive agency attempt",
                  "level": "danger",
                  "detail": "Chat text cannot change who is acting, a permission, a limit or a confirmation. "
                            "Those are set only on their own screens."},
    "claimed_approval": {"code": "INJECTION_DETECTED", "owasp": "LLM01", "label": "Claimed approval",
                         "level": "danger",
                         "detail": "The message says someone has already approved this payment. Approval counts only "
                                   "when the family gives it on their own screen, so nothing was prepared."},
    "indirect": {"code": None, "owasp": "LLM01", "label": "Hidden instruction in a bill", "level": "danger",
                 "detail": "The bill's own text tells the assistant what to do. Bill text is data: it was shown to "
                           "the student as a warning and never followed, and Qwen is never sent it."},
    "markup": {"code": None, "owasp": "LLM05", "label": "Markup in the message", "level": "note",
               "detail": "The message contains HTML or script. It is shown as plain text and never run."},
    "too_long": {"code": "INPUT_TOO_LONG", "owasp": "LLM10", "label": "Oversized message", "level": "danger",
                 "detail": "The message is longer than the limit, so nothing was read or sent to Qwen."},
    "flood": {"code": "TOO_MANY_MESSAGES", "owasp": "LLM10", "label": "Message flood", "level": "danger",
              "detail": "Too many messages in one minute, so this one was not read or sent to Qwen."},
}

# Gate-level refusals that are scams even though no wording gave them away. Labelled for the red alert screen.
GATE_THREATS = {
    "PAYEE_NOT_VERIFIED": {"owasp": None, "label": "Look-alike or unknown account", "level": "danger"},
    "ACCOUNT_CHANGED": {"owasp": None, "label": "Changed bank details", "level": "danger"},
}

REFUSE_KINDS = ("injection", "secret", "system_prompt", "privilege")
MAX_MESSAGE_CHARS = 600


def detect(message: str, money: bool = False):
    """The first attack kind the wording shows, or None. Order matters: an instruction-override is named as that even
    when it also asks for a secret. `money` says the request would move money (claimed approval only counts then)."""
    text = message or ""
    flat = deobfuscate(text)
    if looks_like_injection(text):
        return "injection"
    if _PROMPT_LEAK.search(text) or _PROMPT_LEAK.search(flat):
        return "system_prompt"
    if _SECRET_DATA.search(text) or _SECRET_DATA.search(flat):
        return "secret"
    if _PRIVILEGE.search(text) or _PRIVILEGE.search(flat):
        return "privilege"
    if (_LIMIT_ORDER.search(text) or _LIMIT_ORDER.search(flat)) and not _QUESTION.search(text.strip()):
        return "privilege"
    if money and claims_approval(text):
        return "claimed_approval"
    if _MARKUP.search(text):
        return "markup"
    return None


def describe(kind: str) -> dict:
    """The screen's view of an attack kind: label, OWASP id and name, level, what the code did."""
    k = KINDS[kind]
    return {"kind": kind, "label": k["label"], "owasp": k["owasp"], "owasp_name": OWASP.get(k["owasp"]),
            "level": k["level"], "what": k["detail"]}


def for_code(code: str, detected: str = None, blocked: bool = True):
    """The threat to show with a response: a gate-level scam when the refusal says so, else the wording kind that was
    detected (a refusal must carry that kind's own code; markup and a hidden instruction in a bill may come with any answer)."""
    if blocked and code in GATE_THREATS:
        g = GATE_THREATS[code]
        return {"kind": "gate", "label": g["label"], "owasp": g["owasp"], "owasp_name": OWASP.get(g["owasp"]),
                "level": g["level"], "what": None}
    if detected and (detected in ("markup", "indirect") or (blocked and KINDS[detected]["code"] == code)):
        return describe(detected)
    return None
