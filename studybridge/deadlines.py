"""Deadline store and reminder bookkeeping (SQLite, standard library only).

The tuition Deadline Guardian (`StudentFinanceAgent.guardian`) works out what is due and whether the money is there.
This store keeps a copy of that in a small database so a scheduler can compare today with the last check and raise
each reminder once:

    deadlines  one row per unpaid tuition invoice: amount, due date, send-by date, level, and the wallet figures
    reminders  one row per (invoice, level) reached: soon, now, overdue; acknowledged by the student
    advice     advice text already written for an exact set of facts (so the model is not asked twice)

It is a mirror and a log, not a second source of truth: the payment book decides what is payable. `:memory:` is
used unless a file is given (`--db`, `STUDYBRIDGE_DB`, or next to `--state`). Callers hold the sandbox lock, so the
single connection is never used by two threads at once.
"""
import sqlite3

_SCHEMA = """
CREATE TABLE IF NOT EXISTS deadlines (
    invoice_id TEXT PRIMARY KEY, payee TEXT, purpose TEXT, amount TEXT, currency TEXT, due_date TEXT, send_by TEXT,
    level TEXT, funding_balance TEXT, funding_needed TEXT, funding_gap TEXT, updated TEXT);
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT, invoice_id TEXT, level TEXT, text TEXT, created TEXT,
    acked INTEGER NOT NULL DEFAULT 0, UNIQUE (invoice_id, level));
CREATE TABLE IF NOT EXISTS advice (
    key TEXT PRIMARY KEY, text TEXT, source TEXT, cut INTEGER, created TEXT);
"""

REMIND_LEVELS = ("soon", "now", "overdue")


class DeadlineStore:
    def __init__(self, path=":memory:"):
        self.path = str(path)
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(_SCHEMA)

    def clear(self):
        with self.db:
            for table in ("deadlines", "reminders", "advice"):
                self.db.execute(f"DELETE FROM {table}")

    def close(self):
        self.db.close()

    def __del__(self):
        try:
            self.db.close()
        except Exception:
            pass

    # -------------------------------------------------------------- the scheduler's check
    def sync(self, g: dict, now_iso: str) -> list:
        """Copy the guardian's current view into `deadlines`, drop paid invoices, and raise each new reminder once.

        Returns the reminders created by this call (each a dict with id, invoice_id, level, text, created).
        """
        new = []
        with self.db:
            keep = [i["invoice_id"] for i in g["items"]]
            marks = ",".join("?" * len(keep)) or "''"
            self.db.execute(f"DELETE FROM deadlines WHERE invoice_id NOT IN ({marks})", keep)
            for i in g["items"]:
                self.db.execute(
                    "INSERT OR REPLACE INTO deadlines VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (i["invoice_id"], i.get("payee"), i.get("purpose"), str(i["amount"]), i["currency"], i["due_date"],
                     i.get("send_by"), i["level"], str(g["funding_balance"]), str(g["funding_needed"]),
                     str(g["funding_gap"]), now_iso))
                if i["level"] in REMIND_LEVELS:
                    text = self._text(i, g)
                    cur = self.db.execute(
                        "INSERT OR IGNORE INTO reminders (invoice_id, level, text, created) VALUES (?,?,?,?)",
                        (i["invoice_id"], i["level"], text, now_iso))
                    if cur.rowcount:
                        new.append({"id": f"RMD-{cur.lastrowid}", "invoice_id": i["invoice_id"], "level": i["level"],
                                    "text": text, "created": now_iso})
        return new

    @staticmethod
    def _text(i: dict, g: dict) -> str:
        if i["level"] == "overdue":
            return f"{i['invoice_id']} was due {i['due_date']}. Contact the university finance office first."
        lead = "Send now" if i["level"] == "now" else "Send soon"
        gap = f" Funds are short by BDT {g['funding_gap']}." if float(g["funding_gap"]) > 0 else ""
        return (f"{lead}: {i['invoice_id']} is due {i['due_date']}; the money must leave by {i.get('send_by')}."
                + gap)

    # -------------------------------------------------------------- reading and acknowledging
    def deadlines(self) -> list:
        return [dict(r) for r in self.db.execute("SELECT * FROM deadlines ORDER BY due_date, invoice_id")]

    def reminders(self, unacked_only: bool = True) -> list:
        q = "SELECT * FROM reminders" + (" WHERE acked = 0" if unacked_only else "") + " ORDER BY id DESC"
        return [{"id": f"RMD-{r['id']}", "invoice_id": r["invoice_id"], "level": r["level"], "text": r["text"],
                 "created": r["created"], "acked": bool(r["acked"])} for r in self.db.execute(q)]

    def ack(self, reminder_id: str) -> bool:
        try:
            rid = int(str(reminder_id).split("-")[-1])
        except ValueError:
            return False
        with self.db:
            return self.db.execute("UPDATE reminders SET acked = 1 WHERE id = ? AND acked = 0", (rid,)).rowcount > 0

    # -------------------------------------------------------------- advice cache
    def get_advice(self, key: str):
        r = self.db.execute("SELECT text, source, cut, created FROM advice WHERE key = ?", (key,)).fetchone()
        return dict(r) if r else None

    def put_advice(self, key: str, text: str, source: str, cut: int, created: str):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO advice VALUES (?,?,?,?,?)", (key, text, source, cut, created))
