"""Sandbox clock.

Approval windows (24 h), allowance validity (72 h) and the 2-minute
confirmation all read this clock, so tests, the scripted run and the demo
can move time forward ("time travel") without waiting.
"""
import time
from datetime import date, datetime, timedelta


class SandboxClock:
    def __init__(self, start: datetime = None, ticking: bool = False):
        self._start = start or datetime.now().replace(microsecond=0)
        self._real0 = time.time()
        self._offset = timedelta(0)
        self.ticking = ticking

    def now(self) -> datetime:
        elapsed = timedelta(seconds=time.time() - self._real0) if self.ticking else timedelta(0)
        return (self._start + elapsed + self._offset).replace(microsecond=0)

    def ts(self) -> float:
        return self.now().timestamp()

    def today(self) -> date:
        return self.now().date()

    def advance(self, hours: float = 0, minutes: float = 0):
        self._offset += timedelta(hours=hours, minutes=minutes)

    def set(self, now: datetime):
        """Continue from `now` (used when a saved state is loaded)."""
        self._start, self._real0, self._offset = now, time.time(), timedelta(0)
