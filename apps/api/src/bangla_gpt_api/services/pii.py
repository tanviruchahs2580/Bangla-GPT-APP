"""Pre-LLM PII redaction.

Student-pasted identifiers (phone numbers, emails, NID-like digit runs) must
never egress to an external model provider.:func:`redact_pii` replaces them
with neutral placeholders and reports how many it removed, so callers can
meter disclosures. Screening (safety refusal) still runs FIRST on the raw
question — redaction only sanitises what is sent upstream, it never hides
abuse from the safety layer.
"""

import re

# Bangladesh mobile (PRIV-001): the operator prefix 01[3-9] plus 8 digits,
# accepting the country code and the separators a guardian actually types --
# `+880 1712-345678`, `(017) 12345678`, `00880 171 234 5678` -- in ASCII or
# Bangla digits. The previous ASCII-only `01[3-9]\d{8}` matched none of the
# separated spellings, so those digits reached the upstream model verbatim;
# `+8801712345678` and `০১৭১২৩৪৫৬৭৮` fell through to the NID rule, which
# redacted them under the wrong metering kind.
#
# ReDoS discipline (F-076): every optional group is bounded and unnested and
# the only repetition is a fixed {8}, so the scan is linear. Do NOT rewrite
# the separator class as a repeated alternation such as `(\s|-|\.)*` -- nesting
# a quantifier inside a repetition is what made the email pattern quadratic.
#
# Known residual: in the doubly-zeroed `+880 017 ...` spelling the match starts
# at the local number, leaving the `+880 ` prefix outside the placeholder. All
# digits are still redacted. Widening the prefix group was traded away to keep
# this the exact shape validated against the positive/negative corpora.
_MOBILE_RE = re.compile(
    r"(?<!\d)"
    r"(?:(?:\+|00)?[8\u09ee]{2}[ \-./]?)?"
    r"\(?[0\u09e6]?[ \-./]?"
    r"[1\u09e7][3-9\u09e9-\u09ef]\)?"
    r"(?:[ \-./]?\d){8}"
    r"(?!\d)"
)
# Bangladesh landline (PRIV-001 follow-up): a Dhaka-style `02` plus 7-8
# subscriber digits, or a three-digit regional area code (e.g. `031`) plus 6-7
# subscriber digits — optionally behind the +880/00880 country code, in ASCII
# or Bangla digits. The mobile rule requires the 01[3-9] prefix and the NID
# rule needs 10+ CONTIGUOUS digits, so `+880 2 9661234` (9 separated digits)
# egressed verbatim. Same ReDoS discipline as the mobile rule: bounded,
# unnested, fixed repetitions only. Redactions meter under the `phone` kind.
_LANDLINE_RE = re.compile(
    r"(?<!\d)"
    r"(?:"
    r"(?:(?:\+|00)?[8\u09ee]{2}[ \-./]?[0\u09e6]?[ \-./]?[2\u09e8][ \-./]?\d{7,8})"
    r"|[0\u09e6][ \-./]?(?:[2\u09e8][ \-./]?\d{7,8}|[3-9\u09e9-\u09ef]\d[ \-./]?\d{6,7})"
    r")"
    r"(?!\d)"
)
# Email addresses (ASCII local/domain; IDN is out of scope for pasted PII).
_EMAIL_RE = re.compile(r"(?<![\w.+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![\w.-])")
# NID / birth-registration-like runs: 10-17 consecutive digits. Deliberately
# NOT matching short runs (years, class levels, chapter numbers) to avoid
# mangling legitimate curriculum questions.
_NID_RE = re.compile(r"(?<!\d)\d{10,17}(?!\d)")

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # Order is documented and pinned (test_pattern_order_keeps_an_adjacent_
    # address_intact): phone before email, on purpose — a pasted
    # "number@domain" is a phone glued to a domain and redacts its digits
    # under the phone kind.
    ("phone", _MOBILE_RE),
    ("phone", _LANDLINE_RE),
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
