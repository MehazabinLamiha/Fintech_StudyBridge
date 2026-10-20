"""Banglish (Bangla in Latin letters) and Bangla words for the rules reader.

Only the rules reader uses these lists. Qwen is not asked to read Bangla any better than before, and it still owns
no number, payee or approval: the same gates run on whatever the reader finds. Bangla digits (০-৯) already read as
numbers because Python's \\d matches them; tests/test_payments.py checks that.

The lists are deliberately small and common. They are a first draft: a native speaker should add the spellings
students really type. A word here can only make the reader pick an intent; money still needs a stored invoice or
saved payee, the family's approval where it applies, and the student's own confirmation.
"""
import re

# Words that mean "pay / send": "canteen e 38 yuan dao", "INV-0003 পেমেন্ট করো", "ক্যান্টিনে ৩৮ ইউয়ান দাও".
PAY_ROMAN = ("dao", "dau", "den", "deo", "pathao", "pathan", "pathiye", "poriSodh", "porishodh", "poroshodh")
PAY_BANGLA = ("পাঠাও", "পাঠান", "পাঠিয়ে", "দাও", "দিয়ে দাও", "দিন না", "পেমেন্ট", "পরিশোধ")
DO_ROMAN = ("koro", "kore", "korun", "koren", "korben")

# Words that mean the message is about something else, so a bare "dao" is not "pay": "rate dao", "100 usd er dam dao".
NOT_PAY_ROMAN = ("rate", "dam", "dor", "quote", "convert", "exchange", "balance", "status")
NOT_PAY_BANGLA = ("রেট", "দাম", "দর", "রূপান্তর", "ব্যালেন্স", "অবস্থা")

HELP = ("shahajjo", "sahajjo", "shahajyo", "সাহায্য", "কী করতে পারো", "কি করতে পারো")
WALLET = ("koto ache", "koto taka", "koto achhe", "কত আছে", "কত টাকা আছে", "ব্যালেন্স", "ওয়ালেট")
STATUS = ("obostha", "অবস্থা", "অপেক্ষমাণ")
TUITION = ("টিউশন",)
RATE = ("রেট", "দর", "rate koto", "dam koto", "dor koto")
CONVERT = ("রূপান্তর", "বদলাও", "convert koro", "exchange koro")
ALLOWANCE = ("অনুমতি", "onumoti", "allowance chai")
# A person typing that they approve (the assistant cannot approve; this only sharpens the refusal).
APPROVE_SAYING = re.compile(r"(approve|অনুমোদন)\s*(korlam|korchi|kore dilam|করলাম|করছি|করে দিলাম)|"
                            r"আমি\s*(পরিবার|family)", re.IGNORECASE)


def _roman(m: str, words) -> bool:
    return any(re.search(r"(?<![a-z0-9])" + re.escape(w.lower()) + r"(?![a-z0-9])", m) for w in words)


def _bangla(m: str, words) -> bool:
    return any(w in m for w in words)


def says(m: str, roman=(), bangla=()) -> bool:
    return _roman(m, roman) or _bangla(m, bangla)


def pays(m: str) -> bool:
    """'dao', 'pathao', 'পেমেন্ট করো' and the like, unless the message is clearly about a rate, balance or status."""
    if says(m, NOT_PAY_ROMAN, NOT_PAY_BANGLA):
        return False
    if says(m, PAY_ROMAN, PAY_BANGLA):
        return True
    return _roman(m, ("payment",)) and _roman(m, DO_ROMAN)
