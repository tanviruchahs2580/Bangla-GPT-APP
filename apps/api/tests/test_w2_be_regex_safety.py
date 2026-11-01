"""W2/BE-24 (F-076): adversarial long inputs stay inside a time budget.

The audit timed repository regexes against 20 000-char adversarial inputs and
found quadratic scans: the log-redaction email pattern (10 s), the
government-report email scan (8 s) and the JSON code-fence strip (4 s). The
patterns are now bounded/linear; these tests run each of them against the
same shape with a hard budget so a rewrite cannot reintroduce a ReDoS.

The budgets are deliberately generous (a CI runner is slower than a dev box):
under 1 s where the fixed code measures tens of milliseconds, against a
25 s pre-fix worst case.
"""

import time

from bangla_gpt_api.logging_config import _EMAIL_VALUE_PATTERN, redact_value
from bangla_gpt_api.services import govt_report
from bangla_gpt_api.services.generators._json import strip_code_fences

LONG_CHARS = 20_000
BUDGET_SECONDS = 1.0

#: Boundary-rich word run: every '.' is a word boundary, which is the shape
#: that made the anchored email quantifiers backtrack per position.
BOUNDARY_RUN = "a." * (LONG_CHARS // 2)
WORD_RUN = "a" * LONG_CHARS
SPACE_RUN = " " * LONG_CHARS


def _seconds(fn) -> float:
    started = time.perf_counter()
    fn()
    return time.perf_counter() - started


def test_log_email_pattern_is_linear_on_a_long_word_run() -> None:
    elapsed = _seconds(lambda: _EMAIL_VALUE_PATTERN.search(BOUNDARY_RUN))
    assert elapsed < BUDGET_SECONDS, f"{elapsed:.3f}s on {len(BOUNDARY_RUN)} chars"


def test_redaction_of_a_long_nonsense_value_is_linear() -> None:
    elapsed = _seconds(lambda: redact_value({"detail": BOUNDARY_RUN}))
    assert elapsed < BUDGET_SECONDS, f"{elapsed:.3f}s on {len(BOUNDARY_RUN)} chars"


def test_government_report_email_scan_is_linear() -> None:
    elapsed = _seconds(lambda: govt_report.pii_violations(BOUNDARY_RUN))
    assert elapsed < BUDGET_SECONDS, f"{elapsed:.3f}s on {len(BOUNDARY_RUN)} chars"
    # A value with no '@' skips the pattern entirely and must be fast, too.
    elapsed = _seconds(lambda: govt_report.pii_violations(WORD_RUN))
    assert elapsed < BUDGET_SECONDS, f"{elapsed:.3f}s on {len(WORD_RUN)} chars"


def test_fence_strip_is_linear_on_a_whitespace_run() -> None:
    """A pure whitespace completion: the pre-fix pattern took 3.8 s here."""
    elapsed = _seconds(lambda: strip_code_fences(SPACE_RUN))
    assert elapsed < BUDGET_SECONDS, f"{elapsed:.3f}s on {len(SPACE_RUN)} chars"


def test_fence_strip_keeps_its_old_semantics() -> None:
    """The string-based stripper must agree with the regex it replaced."""
    import re

    old = re.compile(r"^```(?:json)?\s*|\s*```\s*$")
    cases = [
        '```json\n{"a": 1}\n```',
        '```{"a": 1}```',
        '  {"a": 1}  ',
        '```\n  {"a": 1}\n```\n',
        '{"a": "``` b"}',
        '{"a": 1}\n```',
        "``` {a}",
        "```json{a}",
        "```json",
        '{"a": 1}',
        '{"a": 1}\n``` tail',
    ]
    for text in cases:
        assert strip_code_fences(text) == old.sub("", text.strip()), text


def test_email_redaction_still_matches_real_addresses() -> None:
    """The bounded pattern must not lose the detection the guard relies on."""
    assert redact_value({"detail": "kid@example.com"})["detail"] == "[redacted]"
    assert redact_value({"detail": "a.b-c+tag@sub.example.co.bd"})["detail"] == "[redacted]"
    # Not an address: no '@'.
    assert redact_value({"detail": "a.b-c+tag.example.co.bd"})["detail"] != "[redacted]"
