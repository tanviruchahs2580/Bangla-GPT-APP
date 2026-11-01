"""F-161 / TEST-03: the suite's wall-clock sleeps are a reviewed list.

Every literal sleep >= 1s is listed with the reason it cannot be removed. A
new long sleep, or a longer one where a shorter one existed, fails here so the
cost is an explicit decision instead of an accident. The injected-clock
rewrites of the F-05 epoch tests removed the three 1.1s TTL sleeps, the
cache-TTL tests run on an injected monotonic clock, and every deadline-bounded
poll (job runner, mailpit delivery, Redis server TTL) goes through
conftest.poll_until, which owns the suite's one short poll-interval sleep.
"""

from __future__ import annotations

import re
from pathlib import Path

TESTS = Path(__file__).resolve().parent
_SLEEP_RE = re.compile(r"\b(?:_time|time|asyncio)\.sleep\(([0-9.]+)\)")

#: (file, seconds) -> why the wall-clock wait is the test's subject, not slack.
ALLOWED_LONG_SLEEPS: dict[tuple[str, float], str] = {
    ("test_w2_sec_client.py", 1.0): (
        "negative SSRF assertion: the wait is what gives a forbidden fetch time to happen"
    ),
    ("test_round2_budget_and_drain.py", 3600.0): (
        "deliberately never-finishing drain task, cancelled by the test"
    ),
}


def _literal_long_sleeps() -> dict[tuple[str, float], list[int]]:
    found: dict[tuple[str, float], list[int]] = {}
    for path in sorted(TESTS.glob("test_*.py")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            for match in _SLEEP_RE.finditer(line):
                seconds = float(match.group(1))
                if seconds >= 1.0:
                    found.setdefault((path.name, seconds), []).append(lineno)
    return found


def test_every_long_sleep_is_on_the_reviewed_list() -> None:
    found = _literal_long_sleeps()
    unexpected = sorted(key for key in found if key not in ALLOWED_LONG_SLEEPS)
    assert not unexpected, (
        "new wall-clock sleep >= 1s; inject a clock or add it to the reviewed "
        f"list with a reason: {unexpected}"
    )
    missing = sorted(key for key in ALLOWED_LONG_SLEEPS if key not in found)
    assert not missing, f"reviewed sleep no longer present; drop it from the list: {missing}"
