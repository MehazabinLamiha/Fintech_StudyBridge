"""Payment records: one entry per payment made in the sandbox, and what is built from them.

- `receipt_text`: a receipt for one payment (what the student shows the university or landlord in real life;
  here it is labelled as a sandbox receipt).
- `monthly_summary`: spending by category, this month against last month, with a few plain tips written by code.
- `payment_record`: a letter listing rent and university payments and whether each was on time. It is a record,
  not a credit score: it is what a landlord, scholarship office or bank can actually ask to see.

Every number here comes from stored payments and the sample history, never from the model.
"""
from datetime import date
from decimal import Decimal

from .money import D, convert_mid, q

CATEGORY = {"institution": "University", "landlord": "Rent", "merchant": "Shopping", "food": "Food",
            "qr_merchant": "Small QR payments", "person_or_agent": "Agent"}
FIXED = ("Rent", "University")          # bills the student cannot cut; the tips look at the rest
HISTORY_CATEGORY = {"rent": "Rent", "food": "Food", "transport": "Transport", "phone": "Phone", "books": "Books",
                    "electronics": "Shopping", "subscriptions": "Subscriptions"}
SANDBOX_NOTE = "SANDBOX RECEIPT: no real money moved. Not proof of payment to a real university or landlord."
RECORD_NOTE = ("This is a record of bills paid through the StudyBridge sandbox. It is not a credit score, not a "
               "bank statement and not checked by any bank.")


def entry(ref: str, at: str, pay: dict, op: dict, rec: dict) -> dict:
    """One paid payment. `pay` is the Gate 1 result, `op` the confirmed operation, `rec` the wallet's record."""
    if op.get("request_id"):
        approved = f"Family approval {op['request_id']}"
    elif op.get("allowance_id"):
        approved = f"Allowance {op['allowance_id']} from the family"
    elif op.get("counts_family"):
        approved = "Inside today's family daily limit"
    else:
        approved = "Small university fee (no family approval needed)"
    day = at[:10]
    due = pay.get("due")
    return {"ref": ref, "at": at, "date": day, "payee_id": pay["payee_id"], "payee_name": pay["payee_name"],
            "category": CATEGORY.get(pay["payee_type"], "Other"), "invoice_id": pay.get("invoice_id"),
            "purpose": pay.get("purpose"), "due": due, "on_time": (day <= due) if due else None,
            "amount": q(pay["amount"]), "currency": pay["currency"], "debited_bdt": q(D(rec["debited"])),
            "route": rec.get("provider") or "Family-funded card", "fee_bdt": q(D(rec["fee"])) if rec.get("fee") else None,
            "account": rec.get("account"), "approved_by": approved}


def receipt_text(e: dict, owner: dict, family_name: str) -> str:
    lines = [
        "StudyBridge payment receipt",
        SANDBOX_NOTE,
        "",
        f"Reference:   {e['ref']}",
        f"Paid on:     {e['at'].replace('T', ' ')} (sandbox time)",
        f"Student:     {owner['display_name']}, student id {owner.get('student_id', '-')}",
        f"Paid to:     {e['payee_name']}" + (f", account {e['account']}" if e.get("account") else ""),
    ]
    if e.get("invoice_id"):
        lines.append(f"Bill:        {e['invoice_id']}, {e['purpose']}" + (f" (due {e['due']})" if e.get("due") else ""))
    lines += [
        f"Amount:      {e['currency']} {e['amount']:,.2f}",
        f"Funded by:   {family_name}, BDT {e['debited_bdt']:,.2f} debited",
        f"Route:       {e['route']}" + (f", fee BDT {e['fee_bdt']:,.2f}" if e.get("fee_bdt") is not None else ""),
        f"Approved by: {e['approved_by']}; confirmed by the student",
        "",
        "Every check (bill, verified account, documents, limits) was re-run just before paying.",
    ]
    return "\n".join(lines) + "\n"


def _month(d: str) -> str:
    return d[:7]


def _prev_month(m: str) -> str:
    y, mo = int(m[:4]), int(m[5:7])
    return f"{y - 1}-12" if mo == 1 else f"{y}-{mo - 1:02d}"


def spending_rows(entries: list, history: list) -> list:
    """(month, category, CNY, BDT) for every payment and every spending line of the sample history. For a sandbox
    payment the BDT is what actually left the wallet (route, fee and FX margin included), the same figure as on its
    receipt; the sample history has no debit record, so its BDT is the plain exchange-rate value."""
    rows = [(_month(e["date"]), e["category"], convert_mid(D(e["amount"]), e["currency"], "CNY"), D(e["debited_bdt"]))
            for e in entries]
    for t in history:
        amt = D(t["amount"])
        if amt < 0 and t["currency"] != "BDT":
            rows.append((_month(t["date"]), HISTORY_CATEGORY.get(t["category"], "Other"),
                         convert_mid(-amt, t["currency"], "CNY"), convert_mid(-amt, t["currency"], "BDT")))
    return rows


def monthly_summary(entries: list, history: list, today: date) -> dict:
    """This month so far against last month, by category, in CNY (and BDT for the family). Tips are code-written."""
    this_m = today.isoformat()[:7]
    last_m = _prev_month(this_m)
    by, bdt = {}, {}
    for month, cat, cny, taka in spending_rows(entries, history):
        if month in (this_m, last_m):
            when = "this" if month == this_m else "last"
            by.setdefault(cat, {"this": Decimal(0), "last": Decimal(0)})[when] += cny
            bdt.setdefault(cat, {"this": Decimal(0), "last": Decimal(0)})[when] += taka
    cats = sorted(by, key=lambda c: (-(by[c]["this"] + by[c]["last"]), c))
    total_this = sum((v["this"] for v in by.values()), Decimal(0))
    total_last = sum((v["last"] for v in by.values()), Decimal(0))
    tips = []
    flex = {c: v["last"] for c, v in by.items() if c not in FIXED and v["last"] > 0}
    if flex:
        top, flexible = max(flex, key=flex.get), sum(flex.values(), Decimal(0))
        tips.append(f"Rent and university bills are fixed. Everything else came to CNY {flexible:,.0f} last month, "
                    f"and {top} was the biggest part (CNY {flex[top]:,.0f}, {flex[top] / flexible * 100:.0f}%).")
        tips.append(f"Spending 10% less of that saves about CNY {flexible / 10:,.0f} a month "
                    f"(BDT {convert_mid(flexible / 10, 'CNY', 'BDT'):,.0f} of your family's money).")
    for c in cats:
        if by[c]["last"] > 0 and by[c]["this"] > by[c]["last"]:
            tips.append(f"{c} this month (CNY {by[c]['this']:,.0f}) is already above last month "
                        f"(CNY {by[c]['last']:,.0f}).")
    return {"month": this_m, "last_month": last_m,
            "rows": [{"category": c, "this_cny": q(by[c]["this"]), "last_cny": q(by[c]["last"]),
                      "this_bdt": q(bdt[c]["this"]), "last_bdt": q(bdt[c]["last"])} for c in cats],
            "total_this_cny": q(total_this), "total_last_cny": q(total_last),
            "total_this_bdt": q(sum((v["this"] for v in bdt.values()), Decimal(0))),
            "total_last_bdt": q(sum((v["last"] for v in bdt.values()), Decimal(0))), "tips": tips}


def payment_record(entries: list, history: list, owner: dict, today: date) -> dict:
    """Rent and university payments, oldest first, with on-time marks where a due date is stored."""
    rows = [{"date": t["date"], "what": t.get("memo") or "Rent", "to": "Landlord (sample history)",
             "amount": f"{t['currency']} {-D(t['amount']):,.2f}", "on_time": None}
            for t in history if t["category"] == "rent" and D(t["amount"]) < 0]
    rows += [{"date": e["date"], "what": f"{e['purpose']} ({e['invoice_id']})", "to": e["payee_name"],
              "amount": f"{e['currency']} {e['amount']:,.2f}", "on_time": e["on_time"]}
             for e in entries if e["category"] in ("Rent", "University")]
    rows.sort(key=lambda r: r["date"])
    checked = [r for r in rows if r["on_time"] is not None]
    on_time = sum(1 for r in checked if r["on_time"])
    mark = {True: "on time", False: "LATE", None: "no due date stored"}
    lines = ["Payment record", RECORD_NOTE, "",
             f"Student: {owner['display_name']}, {owner.get('university', '')}, student id {owner.get('student_id', '-')}",
             f"Made on: {today.isoformat()} (sandbox date)", ""]
    lines += [f"{r['date']}  {r['amount']:>14}  {r['what']}, to {r['to']}: {mark[r['on_time']]}" for r in rows] or [
        "No rent or university payments yet."]
    lines += ["", f"{len(rows)} payments; " + (f"{on_time} of {len(checked)} with a due date were paid on time."
                                                 if checked else "none has a due date stored yet.")]
    return {"rows": rows, "count": len(rows), "on_time": on_time, "with_due": len(checked),
            "text": "\n".join(lines) + "\n"}
