"""The injectable clock seam (H-14).

Scheduled and retention work must be testable at a boundary ("what happens
exactly at 23:59:59 Asia/Dhaka?", "what does retention do on its cutoff
second?") without monkeypatching :mod:`datetime` globally. This module is the
single seam: production code asks :func:`utcnow` (or :data:`CLOCK`) for the
time; tests install a :class:`FrozenClock` with :func:`set_clock` and restore
it with :func:`reset_clock`.

Two readings, deliberately:

* :meth:`Clock.now` returns **naive UTC** — the house contract every existing
  comparison and column default uses (``_utcnow`` in ``db/models.py``,
  ``jobs._utc_naive_now``).
* :meth:`Clock.now_aware` returns an aware UTC datetime for callers that need
  one (an HTTP ``Date`` header, a trace attribute, arithmetic across a DST
  boundary).

Scope note: this is the seam, not a sweeping rewrite. Callers migrate as they
are touched for other reasons; the bulk migration of the ~90 direct
``datetime.now`` sites is tracked separately (AUD-EF-16).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime, timedelta


class Clock(ABC):
    """Read-only clock interface."""

    @abstractmethod
    def now(self) -> datetime:
        """Current instant as naive UTC (house contract)."""

    def now_aware(self) -> datetime:
        """Current instant as an aware UTC datetime."""
        return self.now().replace(tzinfo=UTC)


class SystemClock(Clock):
    """The production clock: the real system time, always UTC."""

    def now(self) -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)


class FrozenClock(Clock):
    """A test clock pinned to an instant; :meth:`advance` moves it."""

    def __init__(self, instant: datetime) -> None:
        if instant.tzinfo is None:
            instant = instant.replace(tzinfo=UTC)
        self._instant = instant.astimezone(UTC)

    def now(self) -> datetime:
        return self._instant.replace(tzinfo=None)

    def now_aware(self) -> datetime:
        return self._instant

    def advance(self, **delta: float) -> None:
        """Move the clock by ``timedelta(**delta)`` (e.g. ``seconds=30``)."""
        self._instant += timedelta(**delta)


#: Module-level seam. Production reads the real clock; tests call set_clock.
CLOCK: Clock = SystemClock()


def get_clock() -> Clock:
    return CLOCK


def set_clock(clock: Clock) -> None:
    """Install ``clock`` as the process-wide seam (tests only)."""
    global CLOCK  # noqa: PLW0603 - the seam is intentionally module-global
    CLOCK = clock


def reset_clock() -> None:
    set_clock(SystemClock())


def utcnow() -> datetime:
    """Naive-UTC now, read through the seam."""
    return CLOCK.now()
