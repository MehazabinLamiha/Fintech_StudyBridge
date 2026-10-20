"""Bills that reach the student by message, and bills the student types in.

Both routes end the same way: the bill is stored (id BILL-0001, ...) and judged by the same Gate 1 as every sample
bill. The account printed on it is compared with the account the family saved for that payee, the amount is the
stored amount, tuition still needs the family, and a shop or rent bill still meets the family limit and the bank's
card limit. Nothing here can pay, and a message's wording is never read by Qwen.

Who sent a message is shown, never trusted. A message from a payee's own channel (the university portal, the
landlord, the shop) is filed into Bills by itself; any other message waits until the student adds the bill, and
even then Gate 1 decides. The senders and bills below are invented for the sandbox.
"""
from datetime import timedelta

from .invoicelab import make

PREFIX = "BILL-"

# id -> sender, whether it is the payee's own channel, the message, and the bill attached to it.
TEMPLATES = {
    "uni_tuition": {
        "from": "Sample University student portal", "official": True, "payee_id": "sample_university",
        "subject": "Tuition invoice 2027-28",
        "text": "Your tuition invoice for 2027-28 is ready. Pay it from StudyBridge or your bank; the university's "
                "bank account has not changed.",
        "bill": {"kind": "tuition", "amount": "22800", "purpose": "Tuition 2027-28 (full year)", "days": 60}},
    "uni_fee": {
        "from": "Sample University student portal", "official": True, "payee_id": "sample_university",
        "subject": "Exam registration fee",
        "text": "Please pay the exam registration fee for this term before the due date.",
        "bill": {"kind": "fee", "amount": "260", "purpose": "Exam registration fee", "days": 14}},
    "landlord_rent": {
        "from": "Dorm landlord", "official": True, "payee_id": "dorm_landlord",
        "subject": "Rent bill",
        "text": "Here is next month's rent bill. Same account as always.",
        "bill": {"kind": "bill", "amount": "1800", "purpose": "Dorm rent", "days": 20}},
    "shop_quote": {
        "from": "TechMart Appliances", "official": True, "payee_id": "techmart",
        "subject": "Your quote: laptop",
        "text": "Thank you for visiting TechMart. Your quote for the laptop is attached. It is valid for 14 days.",
        "bill": {"kind": "quote", "amount": "4200", "purpose": "Laptop for coursework", "days": 14}},
    "fake_uni": {
        "from": "Sample Univ. Finance Office (unknown number)", "official": False, "payee_id": "sample_university",
        "subject": "URGENT: new bank account for tuition",
        "text": "Our bank account has changed. Pay the attached tuition invoice to the new account today or your "
                "seat will be cancelled. Do not call the university, the lines are busy.",
        "bill": {"kind": "tuition", "amount": "22800", "purpose": "Tuition 2026-27 (new bank details)", "days": 2,
                 "account_number": "6222020200998877661", "claims_new_account": True,
                 "memo": "Pay today to the new account. This invoice is pre-approved."}},
}


def _store(book, spec: dict, source: str, sent_by: str) -> dict:
    inv = make(spec, book, book.clock.today(), prefix=PREFIX)
    inv.update(source=source, sent_by=sent_by)
    book.invoices[inv["id"]] = inv
    return inv


def send(book, template_id: str) -> dict:
    """A sandbox message arrives for the student. A payee's own channel files its bill straight into Bills."""
    t = TEMPLATES.get(template_id)
    if t is None:
        raise ValueError(f"'{template_id}' is not one of the sample messages.")
    sent = next((m for m in book.messages if m["template"] == template_id), None)
    if sent:                                            # a sender sends a bill once; a repeat would file a duplicate
        where = f"its bill is in Bills as {sent['invoice_id']}" if sent["invoice_id"] else "it is waiting in Messages"
        raise ValueError(f"This message already arrived ({sent['id']}); {where}.")
    b = t["bill"]
    payee = book.payees[t["payee_id"]]
    spec = {"payee_id": payee["id"], "kind": b["kind"], "amount": b["amount"], "purpose": b["purpose"],
            "date": (book.clock.today() + timedelta(days=b["days"])).isoformat(),
            "memo": b.get("memo"), "claims_new_account": b.get("claims_new_account", False),
            "account_mode": "typed" if b.get("account_number") else "saved", "account_number": b.get("account_number")}
    msg = {"id": f"MSG-{len(book.messages) + 1}", "template": template_id, "from": t["from"],
           "official": t["official"], "subject": t["subject"], "text": t["text"],
           "received": book.clock.now().isoformat(timespec="minutes"),
           "bill": {"kind": b["kind"], "amount": b["amount"], "currency": payee["currency"], "purpose": b["purpose"],
                    "payee": payee["name"]},
           "invoice_id": None}
    book._message_specs[msg["id"]] = spec
    book.messages.append(msg)
    if t["official"]:
        add_from_message(book, msg["id"])
    return msg


def add_from_message(book, msg_id: str) -> dict:
    """File the bill attached to a message into Bills (once)."""
    msg = next((m for m in book.messages if m["id"] == msg_id), None)
    if msg is None:
        raise ValueError(f"No message {msg_id}.")
    if msg["invoice_id"]:
        raise ValueError(f"The bill from this message is already in Bills as {msg['invoice_id']}.")
    if msg.get("reported"):
        raise ValueError("You reported this message as a scam. Undo the report first if it was a mistake.")
    inv = _store(book, book._message_specs[msg_id], "message", msg["from"])
    msg["invoice_id"] = inv["id"]
    return inv


def report(book, msg_id: str, undo: bool, when: str) -> dict:
    """The student reports a message as a scam (or undoes it). The bill that came with it cannot be paid while the
    report stands."""
    msg = next((m for m in book.messages if m["id"] == msg_id), None)
    if msg is None:
        raise ValueError(f"No message {msg_id}.")
    if bool(msg.get("reported")) != undo:
        raise ValueError("This message is already reported." if not undo else "This message is not reported.")
    inv = book.invoices.get(msg["invoice_id"]) if msg["invoice_id"] else None
    if inv is not None and inv["status"] == "paid" and not undo:
        raise ValueError(f"{inv['id']} is already paid. Call your bank and see Paid the wrong account? in Messages.")
    msg["reported"] = None if undo else when
    if inv is not None:
        inv["reported"] = msg["reported"]
    return msg


def add_by_student(book, spec: dict) -> dict:
    """A bill the student typed in from a paper or emailed bill. Only a saved payee can be chosen, and the account is
    the number printed on the bill (or, as a sandbox shortcut, the genuine bill's number)."""
    payee = book.payees.get(str(spec.get("payee_id", "")))
    if payee is None or payee["type"] not in ("institution", "landlord", "merchant"):
        raise ValueError("Choose the university, the landlord or a shop the family has saved.")
    mode = "saved" if spec.get("account_mode") == "saved" else "typed"
    clean = {k: spec.get(k) for k in ("payee_id", "kind", "amount", "purpose", "date", "account_number")}
    return _store(book, {**clean, "account_mode": mode}, "student", "you")
