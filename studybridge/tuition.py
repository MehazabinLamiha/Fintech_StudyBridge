"""Tuition payment planner.

Universities bill tuition per academic year and expect it in full (the
Chinese university pages the team checked ask for one year's tuition at
registration). Student-file remittances from Bangladesh go against the
university's invoice. So the plan is one transfer per unpaid tuition invoice,
for the full invoice amount; nothing is split.

Algorithm, for every unpaid invoice on the university's verified account:
1. days left = due date - today.
2. Among the routes allowed for tuition (`tuition_ok`), pick the cheapest that can deliver the exact invoice amount at
   least `safety_days` before the due date (closed-form inverse in
   remittance.source_needed()). If none is fast enough, take the fastest and
   mark the invoice URGENT.
3. send by = due date - safety days - that provider's delivery days.
4. Report the total funding need, any gap against the funding balance, and
   how much a 2% exchange-rate move would change the cost.
"""
from datetime import date, timedelta
from decimal import Decimal

from .config import PROVIDERS
from .money import D, norm_ccy, q, to_usd
from .remittance import source_needed

FX_SHOCK = Decimal("0.02")


def _cheapest_provider(target, src, dst, max_delivery_days):
    best = None
    for p in PROVIDERS:
        if not p.get("tuition_ok"):          # tuition goes only by an allowed route (config.PROVIDERS)
            continue
        if p["corridors"] is not None and (src, dst) not in p["corridors"]:
            continue
        if p["delivery_days"] > max_delivery_days:
            continue
        need = source_needed(p, target, src, dst)
        usd = to_usd(need, src)
        if not (p["min_usd"] <= usd <= p["max_usd"]):
            continue
        if best is None or need < best[1]:
            best = (p, need)
    return best


def plan(invoices: list, today: date, balances: dict, funding_ccy: str = "BDT", safety_days: int = 3) -> dict:
    """`invoices`: unpaid tuition invoices (dicts with id, purpose, amount, currency, due)."""
    funding_ccy = norm_ccy(funding_ccy)
    funding_balance = D(balances.get(funding_ccy, 0))
    rows, total, statuses = [], Decimal(0), set()
    for inv in sorted(invoices, key=lambda i: i["due"]):
        amount, ccy = D(inv["amount"]), norm_ccy(inv["currency"])
        due = date.fromisoformat(inv["due"])
        days_left = (due - today).days
        row = {"invoice_id": inv["id"], "purpose": inv["purpose"], "amount": q(amount), "currency": ccy,
               "due_date": due.isoformat(), "days_left": days_left}
        if days_left < 0:
            rows.append({**row, "status": "OVERDUE",
                         "advice": "The due date has passed. Contact the university finance office first."})
            statuses.add("OVERDUE")
            continue
        choice = _cheapest_provider(amount, funding_ccy, ccy, days_left - safety_days)
        status = "ON_TRACK"
        if choice is None:
            choice = _cheapest_provider(amount, funding_ccy, ccy, days_left)
            status = "URGENT"
        if choice is None:
            rows.append({**row, "status": "NO_PROVIDER",
                         "advice": "Your bank cannot deliver this before the due date. Ask the university finance "
                                   "office for a short extension in writing, then send it through your bank at once."})
            statuses.add("NO_PROVIDER")
            continue
        p, need = choice
        send_by = max(today, due - timedelta(days=safety_days + p["delivery_days"]))
        total += need
        rows.append({**row, "status": status, "send_by": send_by.isoformat(), "provider": p["name"],
                     "provider_id": p["id"], "send_amount": q(need), "delivery_days": p["delivery_days"]})
        statuses.add(status)

    gap = max(Decimal(0), total - funding_balance)
    if not rows:
        status = "NOTHING_DUE"
    elif statuses & {"OVERDUE", "NO_PROVIDER", "URGENT"}:
        status = next(s for s in ("OVERDUE", "NO_PROVIDER", "URGENT") if s in statuses)
    else:
        status = "FUNDING_GAP" if gap > 0 else "ON_TRACK"
    return {"status": status, "invoices": rows, "funding_currency": funding_ccy,
            "funding_balance": q(funding_balance), "total_funding_needed": q(total), "funding_gap": q(gap),
            "fx_sensitivity_2pct": q(total * FX_SHOCK), "safety_days": safety_days}
