"""Injectable clock seam for time-dependent tests (E-16 / H-14).

``src`` still calls ``datetime.now(UTC)``/``utcnow()`` directly at many sites
(AUD-EF-16), and the parts that have already migrated read the application's
own seam, :mod:`bangla_gpt_api.db.clock`. This module gives tests both ends of
that:

* :meth:`FixedClock.installed` installs the clock through
  ``bangla_gpt_api.db.clock.set_clock`` -- the modern path, which every
  migrated caller (``services/retention.py``, ``services/mailer.py``,
  ``services/parent_digest.py`` and ``jobs``) honours without knowing about
  the test;
* :meth:`FixedClock.patched` replaces a *module's* ``datetime`` (or ``time``)
  global for callers that have not migrated yet, so a time-dependent test can
  be written against them today without touching the global ``datetime``
  module process-wide.

Usage::

    from conftest_clock import clock            # pytest fixture

    def test_cutoff(db, clock):
        clock.set("2026-06-01T00:00:00+00:00")
        with clock.installed():
            retention.run_retention_sweep(db, settings=..., dry_run=True)

The fixture never leaks: :meth:`installed` restores the previous clock even
when the block raises, and the ``clock`` fixture is per test.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest import mock

import pytest

from bangla_gpt_api.db import clock as app_clock

#: Sentinel meaning "no timezone argument given", so ``now(None)`` keeps the
#: ``datetime.now(None)`` meaning (naive local) distinct from ``now()``.
_UNSET: Any = object()


def _aware(moment: datetime | str) -> datetime:
    """Coerce to an aware UTC instant (naive input is read as UTC)."""
    if isinstance(moment, str):
        moment = datetime.fromisoformat(moment)
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


class _FrozenDatetime(datetime):
    """``datetime`` whose ``now``/``utcnow`` answer from a :class:`FixedClock`.

    Subclassing (rather than replacing the class outright) keeps every other
    constructor and classmethod working, so ``datetime.fromisoformat`` and
    friends inside the patched module still behave.
    """

    _clock: FixedClock | None = None

    @classmethod
    def now(cls, tz: Any = None) -> datetime:  # type: ignore[override]
        clock = cls._clock
        assert clock is not None  # set by FixedClock.patched
        return clock.now(tz)

    @classmethod
    def utcnow(cls) -> datetime:  # type: ignore[override]
        clock = cls._clock
        assert clock is not None
        return clock.now(None)


class _FrozenTime:
    """Stands in for the ``time`` module inside one patched module."""

    def __init__(self, fixed: FixedClock) -> None:
        self._fixed = fixed

    def time(self) -> float:
        return self._fixed.monotonic()

    def monotonic(self) -> float:
        return self._fixed.monotonic()


class FixedClock(app_clock.Clock):
    """A deterministic, advanceable UTC clock that satisfies both seams.

    ``now()`` follows the house contract (naive UTC, like every ``UtcDateTime``
    column and ``db.clock.Clock.now``); ``now(tz)`` mirrors ``datetime.now``
    for the module-patch path.
    """

    #: Monotonic origin: 1970-01-01T00:00:00Z, so ``monotonic()`` is just the
    #: elapsed seconds of the fixed instant.
    EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

    def __init__(self, start: datetime | str = "2026-03-01T09:30:00+00:00") -> None:
        self._instant = _aware(start)

    # -- reading (app_clock.Clock contract) -------------------------------
    @property
    def instant(self) -> datetime:
        """The current moment as an aware UTC datetime."""
        return self._instant

    def now(self, tz: Any = _UNSET) -> datetime:  # type: ignore[override]
        """Current moment; naive UTC unless ``tz`` is given."""
        if tz is _UNSET or tz is None:
            return self._instant.astimezone(UTC).replace(tzinfo=None)
        return self._instant.astimezone(tz)

    def now_aware(self) -> datetime:
        return self._instant

    def monotonic(self) -> float:
        """Monotonic stand-in: seconds elapsed since :attr:`EPOCH`."""
        return (self._instant - self.EPOCH).total_seconds()

    # -- writing ----------------------------------------------------------
    def set(self, moment: datetime | str) -> FixedClock:
        self._instant = _aware(moment)
        return self

    def advance(
        self,
        *,
        seconds: float = 0,
        minutes: float = 0,
        hours: float = 0,
        days: float = 0,
    ) -> FixedClock:
        self._instant += timedelta(seconds=seconds, minutes=minutes, hours=hours, days=days)
        return self

    # -- patching ---------------------------------------------------------
    @contextmanager
    def installed(self):
        """Install this clock into ``bangla_gpt_api.db.clock`` for the block.

        The seam :mod:`bangla_gpt_api.db.clock` documents; restores the
        previous clock on exit, including on exception.
        """
        previous = app_clock.CLOCK
        app_clock.set_clock(self)
        try:
            yield self
        finally:
            app_clock.set_clock(previous)

    @contextmanager
    def patched(self, module: Any, *, name: str = "datetime"):
        """Freeze ``module.<name>`` for the block (legacy call sites).

        ``name="datetime"`` (default) replaces the module's ``datetime`` with a
        frozen subclass; ``name="time"`` replaces its ``time`` reference with a
        stub answering from :meth:`monotonic` (rate-limit windows).
        """
        frozen: Any
        if name == "time":
            frozen = _FrozenTime(self)
        else:
            frozen = type("FrozenDatetime", (_FrozenDatetime,), {"_clock": self})
        with mock.patch.object(module, name, frozen):
            yield self


@pytest.fixture
def clock() -> FixedClock:
    """A fresh :class:`FixedClock` per test (default 2026-03-01 09:30 UTC)."""
    return FixedClock()


@pytest.fixture
def clock_module(monkeypatch: pytest.MonkeyPatch):
    """Factory fixture: ``clock_module(mod_a, mod_b)`` freezes all on one clock."""

    def _patch(*modules: Any) -> FixedClock:
        fixed = FixedClock()
        for module in modules:
            frozen = type("FrozenDatetime", (_FrozenDatetime,), {"_clock": fixed})
            monkeypatch.setattr(module, "datetime", frozen, raising=True)
        return fixed

    return _patch


__all__ = ["FixedClock", "clock", "clock_module"]
