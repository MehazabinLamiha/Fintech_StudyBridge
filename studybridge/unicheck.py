"""University check: what the code can actually check about the student's university and its bills.

It does not predict whether a university will fail; nothing in the sandbox could show that honestly. It reports
facts from stored data (the official payment page list, this year's and last year's tuition invoices, the bills
that ask for another account) and lists the checks a student should make themselves. Each item has a level:
ok, warn (look at it) or info (do it yourself).
"""
from decimal import Decimal

from .money import D

FEE_RISE_WARN_PCT = Decimal(10)          # ASSUMPTION (team design): a rise above this is worth asking about

ASK_YOURSELF = [
    "Ask the international office for the written refund policy before paying a full year.",
    "Check that the university may admit international students: ask the university's international office or "
    "the Chinese embassy in Dhaka.",
    "Warning signs to watch: fees demanded early or same-day, a request to pay a person or an agent, a sudden "
    "fee rise, or news that classes or staff pay have stopped. If you see one, talk to your family before paying.",
]


def _official_for(name: str, universities: dict):
    n = " ".join(str(name or "").lower().replace(",", " ").split())
    for uid, u in universities.items():
        if u["name"].lower() in n:
            return uid, u
    return None, None


def check(owner: dict, book, universities: dict) -> dict:
    items = []
    name = owner.get("university", "")
    uid, uni = _official_for(name, universities)
    if uni:
        items.append({"level": "ok", "title": "Official payment page on file",
                      "detail": f"{uni['name']} publishes its tuition account on {uni['domain']}. Check a bill "
                                f"against it with Check a bill."})
    else:
        items.append({"level": "info", "title": "No official payment page on file",
                      "detail": f"StudyBridge has no official payment page for {name or 'your university'}. Ask the "
                                f"international office for the page on the university's own .edu.cn site."})

    unis = [p for p in book.payees.values() if p["type"] == "institution"]
    tuition = [i for i in book.invoices.values() if i.get("kind") == "tuition"
               and any(i["payee_id"] == p["id"] for p in unis)]
    on_account = [i for i in tuition if i.get("account_number") == book.payees[i["payee_id"]].get("account_number")]
    paid = sorted((i for i in on_account if i["status"] == "paid"), key=lambda i: i.get("due", ""))
    open_ = sorted((i for i in on_account if i["status"] == "open"), key=lambda i: i.get("due", ""))
    if paid and open_:
        last, now = D(paid[-1]["amount"]), D(open_[0]["amount"])
        rise = (now - last) / last * 100 if last else Decimal(0)
        level = "warn" if rise > FEE_RISE_WARN_PCT else "ok"
        items.append({"level": level, "title": "Tuition change from last year",
                      "detail": f"{open_[0]['id']}: CNY {now:,.2f}, against CNY {last:,.2f} last year "
                                f"({rise:+.1f}%)." + (" Ask the university why before paying." if level == "warn"
                                                      else "")})
        items.append({"level": "ok", "title": "Same bank account as last year",
                      "detail": "This year's tuition bill asks for the account your family already saved and paid "
                                "last year."})
    other = [i for i in book.invoices.values() if i["status"] == "open" and i.get("kind") == "tuition"
             and i not in on_account]
    if other:
        items.append({"level": "warn", "title": f"{len(other)} tuition bill{'s' if len(other) > 1 else ''} ask for "
                                                f"another account",
                      "detail": ", ".join(sorted(i["id"] for i in other)) + ". Do not pay them: the code blocks them, "
                                "and the university's own bill is the one to pay."})
    items += [{"level": "info", "title": "Check yourself", "detail": t} for t in ASK_YOURSELF]
    worst = "warn" if any(i["level"] == "warn" for i in items) else "ok"
    return {"university": name, "official_id": uid, "level": worst, "items": items}
