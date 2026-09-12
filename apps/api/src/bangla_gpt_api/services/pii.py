"""Pre-LLM PII redaction (PRIV-001).

Student-pasted identifiers (phone numbers, emails, NID-like digit runs) must
never egress to an external model provider. :func:`redact_pii` replaces them
with neutral placeholders and reports how many it removed, so callers can
meter disclosures. Screening (safety refusal) still runs FIRST on the raw
question — redaction only sanitises what is sent upstream, it never hides
abuse from the safety layer.
"""

import re

# Bangladesh mobile: 01[3-9] + 8 digits (covers 013-019 ranges).
_MOBILE_RE = re.compile(r"(?<!\d)01[3-9]\d{8}(?!\d)")
# Email addresses (ASCII local/domain; IDN is out of scope for pasted PII).
_EMAIL_RE = re.compile(r"(?<![\w.+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![\w.-])")
# NID / birth-registration-like runs: 10-17 consecutive digits. Deliberately
# NOT matching short runs (years, class levels, chapter numbers) to avoid
# mangling legitimate curriculum questions.
_NID_RE = re.compile(r"(?<!\d)\d{10,17}(?!\d)")

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("phone", _MOBILE_RE),
    ("email", _EMAIL_RE),
    ("nid", _NID_RE),
)


def redact_pii(text: str) -> tuple[str, dict[str, int]]:
    """Replace PII spans with ``[phone redacted]``-style placeholders.

    Returns ``(redacted_text, counts_by_kind)``. Idempotent: running it twice
    changes nothing the second time (placeholders contain no digits/@).
    """
    counts = {"phone": 0, "email": 0, "nid": 0}

    def _sub(pattern: re.Pattern[str], label: str, source: str) -> str:
        def _repl(match: re.Match[str]) -> str:
            counts[label] += 1
            return f"[{label} redacted]"

        return pattern.sub(_repl, source)

    out = text
    for label, pattern in _PATTERNS:
        out = _sub(pattern, label, out)
    return out, counts


def redacted_total(counts: dict[str, int]) -> int:
    """Total spans removed (sum over kinds)."""
    return sum(counts.values())
