"""The family PIN: a lock on the Family screen.

The sandbox has no user login (a stated weakness), so anyone holding the phone could open the Family tab and approve
their own request. Once the family sets a PIN, every family action needs the screen unlocked with it first. An unlock
lasts UNLOCK_MINUTES of sandbox time; wrong tries lock it. Only a salted PBKDF2 hash is kept. Until a PIN is set,
nothing changes (the stories and tests run without one).

This makes self-approval harder; it is not real authentication, and the docs say so.
"""
import hashlib
import hmac
import secrets

from ..reasons import PaymentBlocked

UNLOCK_MINUTES = 10
MAX_FAILS = 5
LOCK_MINUTES = 15
OPEN_ACTIONS = ("unlock", "lock")       # the only family actions allowed while locked


def _hash(pin: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt), 200_000).hex()


class FamilyPin:
    def __init__(self, clock):
        self.clock = clock
        self.record = None           # {"salt", "hash"}; never the PIN itself
        self.unlocked_until = None
        self.fails = []
        self.locked_until = None

    @property
    def is_set(self) -> bool:
        return self.record is not None

    def unlocked(self) -> bool:
        return not self.is_set or (self.unlocked_until is not None and self.clock.ts() < self.unlocked_until)

    def require(self, action: str):
        """Raise unless this family action may run now. Each allowed action extends the unlock."""
        if action in OPEN_ACTIONS or not self.is_set:
            return
        if not self.unlocked():
            raise PaymentBlocked("FAMILY_LOCKED", "The Family screen is locked. Type the family PIN to unlock it.")
        self.unlocked_until = self.clock.ts() + UNLOCK_MINUTES * 60

    def _check(self, pin):
        now = self.clock.ts()
        if self.locked_until and now < self.locked_until:
            raise PaymentBlocked("PIN_LOCKED", f"Too many wrong PINs. Try again in "
                                               f"{int(self.locked_until - now) // 60 + 1} minutes.")
        if hmac.compare_digest(_hash(str(pin or ""), self.record["salt"]), self.record["hash"]):
            self.fails, self.locked_until = [], None
            return
        self.fails = [t for t in self.fails if now - t < LOCK_MINUTES * 60] + [now]
        left = MAX_FAILS - len(self.fails)
        if left <= 0:
            self.fails, self.locked_until = [], now + LOCK_MINUTES * 60
            raise PaymentBlocked("PIN_LOCKED", f"Too many wrong PINs. Locked for {LOCK_MINUTES} minutes.")
        raise PaymentBlocked("PIN_WRONG", f"Not the family PIN. {left} {'try' if left == 1 else 'tries'} left.")

    def unlock(self, pin):
        if not self.is_set:
            raise PaymentBlocked("INVALID_CHOICE", "No family PIN is set.")
        self._check(pin)
        self.unlocked_until = self.clock.ts() + UNLOCK_MINUTES * 60

    def lock(self):
        self.unlocked_until = None

    def set(self, pin, current=None) -> bool:
        """Set, change or (with an empty PIN) remove it. Changing or removing needs the current PIN.
        Returns True if a PIN is set afterwards."""
        if self.is_set:
            self._check(current)
        pin = str(pin or "").strip()
        if not pin:
            if not self.is_set:
                raise PaymentBlocked("INVALID_CHOICE", "There is no family PIN to remove.")
            self.record, self.unlocked_until = None, None
            return False
        if not (pin.isdigit() and 4 <= len(pin) <= 8) or len(set(pin)) == 1:
            raise PaymentBlocked("INVALID_CHOICE", "Choose a PIN of 4 to 8 digits that is not one repeated digit.")
        salt = secrets.token_hex(8)
        self.record = {"salt": salt, "hash": _hash(pin, salt)}
        self.unlocked_until = self.clock.ts() + UNLOCK_MINUTES * 60       # whoever set it stays in for now
        return True

    def view(self) -> dict:
        left = int(self.unlocked_until - self.clock.ts()) if self.is_set and self.unlocked() else 0
        return {"set": self.is_set, "unlocked": self.unlocked(), "seconds_left": max(0, left)}

    def dump(self) -> dict:
        return {"record": self.record, "unlocked_until": self.unlocked_until, "fails": self.fails,
                "locked_until": self.locked_until}

    def load(self, data: dict):
        data = data or {}
        self.record, self.unlocked_until = data.get("record"), data.get("unlocked_until")
        self.fails, self.locked_until = list(data.get("fails", [])), data.get("locked_until")
