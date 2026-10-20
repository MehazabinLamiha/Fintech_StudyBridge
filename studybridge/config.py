"""Static configuration for the StudyBridge sandbox.

Every rate, fee and limit in this file is ILLUSTRATIVE SANDBOX DATA. It is not
a live quote from any real provider. A production deployment replaces
MID_PER_USD with a licensed rate feed and PROVIDERS with provider APIs.
"""
from decimal import Decimal as D

HOME_CURRENCY = "BDT"
SUPPORTED_CURRENCIES = ("BDT", "CNY", "USD")     # a Bangladeshi student in China needs these three

CURRENCY_ALIASES = {
    "BDT": "BDT", "TAKA": "BDT", "TK": "BDT", "৳": "BDT",
    "CNY": "CNY", "RMB": "CNY", "YUAN": "CNY", "¥": "CNY",
    "USD": "USD", "DOLLAR": "USD", "DOLLARS": "USD", "$": "USD",
    # Bangla script (first draft; see bangla.py)
    "টাকা": "BDT", "ইউয়ান": "CNY", "রেনমিনবি": "CNY", "ডলার": "USD",
}

# Units of each currency per 1 USD (sandbox mid-market snapshot).
MID_PER_USD = {
    "USD": D("1"),
    "BDT": D("134.90"),
    "CNY": D("7.10"),
}
RATE_SOURCE = "SANDBOX snapshot (illustrative, not a live quote)"

# Spread charged on conversions inside the StudyBridge wallet.
WALLET_FX_SPREAD = D("0.004")

# Fictional provider archetypes. Names are deliberately generic so no real
# company's pricing is misrepresented. Only "tuition_ok" routes may carry tuition: the student's AD bank (student
# file), per Bangladesh Bank FEPD-1 Circular No. 40 (30 Sep 2026) para 10. (A payment company the university names
# in the admission letter is also allowed; no sample university names one.)
PROVIDERS = [
    {
        "id": "bank_swift", "name": "Your AD bank (student file)",
        "fixed_fee_usd": D("25"), "pct_fee": D("0"), "fx_margin": D("0.025"),
        "delivery_days": 3, "min_usd": D("50"), "max_usd": D("50000"),
        "corridors": None, "tuition_ok": True,
    },
    {
        "id": "digital_a", "name": "Digital transfer service A",
        "fixed_fee_usd": D("1.50"), "pct_fee": D("0.0045"), "fx_margin": D("0.004"),
        "delivery_days": 1, "min_usd": D("10"), "max_usd": D("10000"),
        "corridors": None,
    },
    {
        "id": "cash_b", "name": "Cash-pickup network B",
        "fixed_fee_usd": D("8"), "pct_fee": D("0.01"), "fx_margin": D("0.015"),
        "delivery_days": 0, "min_usd": D("5"), "max_usd": D("3000"),
        "corridors": None,
    },
    {
        "id": "wallet_c", "name": "Mobile wallet C",
        "fixed_fee_usd": D("0"), "pct_fee": D("0.015"), "fx_margin": D("0.008"),
        "delivery_days": 0, "min_usd": D("1"), "max_usd": D("1000"),
        "corridors": {("BDT", "CNY"), ("BDT", "USD")},
    },
]

# Money-movement guardrails, expressed in HOME_CURRENCY.
LIMITS = {
    "per_tx_home": D("450000"),
    "daily_home": D("600000"),
    # Tuition on a stored invoice to the verified university account, approved by the family, has its own cap,
    # above a year of tuition at real programmes (MBBS included) and far below laundering-sized "tuition".
    # ASSUMPTION (team design, illustrative).
    "tuition_per_tx_home": D("2500000"),
}
CONFIRM_TTL_SECONDS = 120          # the student's final confirmation: 2 minutes, single use
CONFIRM_MAX_FAILS = 5              # unknown confirmation ids within the window before confirming is locked
CONFIRM_LOCK_SECONDS = 60          # the window, and how long the lock lasts (sandbox clock)

# Payment settings (plan v3). All are ASSUMPTIONS (team design, illustrative).
# The bank limit is applied as a DAILY total of card spending: a team design
# that is stricter than the public rule found (USD 300 per transaction).
PAYMENT = {
    "currency": "CNY",
    "family_limit_min_cny": D("100"),        # the family types its own daily limit within this range
    "family_limit_max_cny": D("5000"),
    "family_limit_default_cny": D("500"),
    "bank_daily_limit_usd": D("300"),        # the default; the bank can change it on its own screen
    "bank_limit_min_usd": D("100"),
    "bank_limit_max_usd": D("1000"),
    "exempt_cap_cny": D("300"),              # food and QR payments, each; fixed, the family cannot change it
    "family_approval_hours": 24,
    "allowance_default_hours": 72,
    "allowance_max_hours": 7 * 24,
    "max_open_allowances": 3,
    "allowance_headroom_max_pct": 10,        # the family may approve up to this much above the quote (price changes)
    "monthly_allowance_max_months": 6,       # rent only; one payment per calendar month
    "account_change_hold_hours": 24,         # wait after the family's phone check
    "limit_raise_days_ahead": 7,             # a one-day raise can be booked up to 7 days ahead
    "safe_word_from_cny": D("10000"),        # with a family safe word set, approving this much or more needs it
    "safe_word_max_fails": 3,                # wrong tries before the safe word is locked
    "safe_word_lock_minutes": 15,
    "new_payee_hold_hours": 48, "duplicate_window_hours": 24,              # a payee the family has just saved cannot be paid until this has passed
}
# Payee types and whether a stored invoice / bill / quote is required.
PAYEE_TYPES = {
    "institution": True,        # tuition path, verified account only
    "landlord": True,           # monthly rent bill
    "merchant": True,           # price quote
    "qr_merchant": False,       # name-only check, capped
    "food": False,              # canteen, groceries, capped
    "person_or_agent": True,    # blocked for tuition; only the family saves one
}
EXEMPT_TYPES = {"qr_merchant", "food"}

OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = "qwen2.5:7b"
# Hosted option (Groq free tier, OpenAI-style API). The model id must match the provider's model list; `available()`
# checks it. The local call budget stays under Groq's free limits (30 requests a minute, 1,000 a day, read 16 Oct 2026).
GUARDIAN_SOON_DAYS = 7   # the Home screen calls a tuition invoice "soon" when it must be sent within this many days
HOSTED_LLM = {"url": "https://api.groq.com/openai/v1", "model": "qwen/qwen3.8-27b", "per_minute": 20, "per_day": 800}
