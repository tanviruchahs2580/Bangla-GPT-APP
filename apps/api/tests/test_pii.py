"""pre-LLM PII redaction.

Pasted phones/emails/NID-like digit runs must never reach an upstream model
provider. The redactor runs at the prompt-build boundary (services/tutor.py);
safety screening still sees the RAW question first, so abuse detection is
unaffected. Curriculum numerals (years, class levels, chapters) must survive.
"""

import pytest

from bangla_gpt_api.metrics import PII_REDACTED_TOTAL
from bangla_gpt_api.services.pii import redact_pii, redacted_total
from bangla_gpt_api.services.tutor import build_evidence_prompt


def test_redacts_bd_mobile_email_and_nid() -> None:
    text, counts = redact_pii("আমার নম্বর 01712345678, মেইল karim@example.com, NID 19901234567890123")
    assert "01712345678" not in text
    assert "karim@example.com" not in text
    assert "19901234567890123" not in text
    assert counts == {"phone": 1, "email": 1, "nid": 1}
    assert redacted_total(counts) == 3
    assert "[phone redacted]" in text
    assert "[email redacted]" in text
    assert "[nid redacted]" in text


def test_leaves_curriculum_numerals_alone() -> None:
    for benign in [
        "৬ষ্ঠ শ্রেণির বিজ্ঞান ৩য় অধ্যায় কী?",
        "১৯৭১ সালে কী হয়েছিল?",
        "x + y = 10 হলে x কত?",
        "class 6 science chapter 3",
        "২০২৪ সালের পাঠ্যবই",
    ]:
        text, counts = redact_pii(benign)
        assert text == benign, benign
        assert redacted_total(counts) == 0


def test_redaction_is_idempotent() -> None:
    once, _ = redact_pii("call 01812345678 now 01812345678")
    twice, counts2 = redact_pii(once)
    assert twice == once
    assert redacted_total(counts2) == 0


def test_evidence_prompt_strips_pii_and_meters_it() -> None:
    before = PII_REDACTED_TOTAL.labels(kind="phone")._value.get()
    prompt = build_evidence_prompt(
        [],
        "আমার ফোন 01987654321, ভগ্নাংশ কী?",
        history=[{"role": "user", "content": "আগে 01611111111 দিয়েছিলাম"}],
    )
    assert "01987654321" not in prompt
    assert "01611111111" not in prompt
    assert "[phone redacted]" in prompt
    # question + one history turn = 2 removals metered
    after = PII_REDACTED_TOTAL.labels(kind="phone")._value.get()
    assert after - before == 2


def test_evidence_prompt_without_pii_is_unchanged() -> None:
    prompt = build_evidence_prompt([], "ভগ্নাংশ কী?", history=None)
    assert "ভগ্নাংশ কী?" in prompt
    assert "redacted" not in prompt


# ---------------------------------------------------------------------------
# F-162: the mutation survivors were all boundary conditions of these three
# patterns. Each case below fails if its boundary moves.
# ---------------------------------------------------------------------------


def test_phone_needs_non_digit_boundaries_but_the_nid_rule_still_catches() -> None:
    """A digit on either side makes it a longer run, not a mobile number.

    Without the lookarounds the phone pattern would fire inside a 12-digit
    run and count a second redaction (and the remaining digits would be
    mangled differently).
    """
    trailing, count_trailing = redact_pii("ref 017123456789 end")
    assert count_trailing == {"phone": 0, "email": 0, "nid": 1}, trailing
    leading, count_leading = redact_pii("ref 1017123456789 end")
    assert count_leading == {"phone": 0, "email": 0, "nid": 1}, leading


def test_email_requires_a_two_character_tld() -> None:
    assert redact_pii("mail a@b.cö here")[1]["email"] == 0
    assert redact_pii("mail a@b.co here")[1]["email"] == 1
    long_tld = "".join(["user@example.", "c" * 63])
    assert redact_pii(long_tld)[1]["email"] == 1


def test_nid_run_length_bounds_are_exact() -> None:
    nine, nine_counts = redact_pii("id 123456789 ok")
    assert nine_counts["nid"] == 0, nine
    ten, ten_counts = redact_pii("id 1234567890 ok")
    assert ten_counts["nid"] == 1, ten
    seventeen, seventeen_counts = redact_pii("id " + "1" * 17 + " ok")
    assert seventeen_counts["nid"] == 1, seventeen
    eighteen, eighteen_counts = redact_pii("id " + "1" * 18 + " ok")
    assert eighteen_counts["nid"] == 0, eighteen


def test_pattern_order_keeps_an_adjacent_address_intact() -> None:
    """The phone pass runs before the email pass by design.

    A pasted "number@domain" is a phone glued to a domain, not an address:
    redacting the phone first leaves "[phone redacted]@example.com", which the
    email pattern cannot match. Swapping the order would label the pair an
    email and leave the phone digits in the text.
    """
    text, counts = redact_pii("যোগাযোগ 01712345678@example.com")
    assert counts == {"phone": 1, "email": 0, "nid": 0}, text
    assert "01712345678" not in text


# ---------------------------------------------------------------------------
# PRIV-001: the spellings a guardian actually types. Every one of these was
# reproduced reaching the upstream model verbatim before the pattern was
# widened -- the ASCII-only ``01[3-9]\d{8}`` matched none of the separated
# forms. Each case below fails if the pattern narrows again.
# ---------------------------------------------------------------------------

#: One number (01712-345678) in every spelling seen in pasted contact text:
#: local and E.164, ASCII and Bangla digits, each separator the keypad emits.
PHONE_SPELLINGS = [
    "01712345678",
    "01712-345678",
    "017 12345678",
    "017 1234 5678",
    "(017) 12345678",
    "(017)-1234-5678",
    "017-1234-5678",
    "017.1234.5678",
    "00880 1712 345678",
    "008801712345678",
    "880-1712-345678",
    "+8801712345678",
    "+880 1712-345678",
    "০১৭১২৩৪৫৬৭৮",
    "০১৭-১২৩৪-৫৬৭৮",
]


@pytest.mark.parametrize("spelling", PHONE_SPELLINGS)
def test_every_phone_spelling_redacts_as_phone(spelling: str) -> None:
    text, counts = redact_pii(spelling)
    assert text == "[phone redacted]", spelling
    assert counts == {"phone": 1, "email": 0, "nid": 0}, spelling


@pytest.mark.parametrize("spelling", PHONE_SPELLINGS)
def test_every_phone_spelling_is_idempotent(spelling: str) -> None:
    once, _ = redact_pii(spelling)
    twice, counts2 = redact_pii(once)
    assert twice == once, spelling
    assert redacted_total(counts2) == 0, spelling


def test_e164_and_bangla_digit_phones_are_metered_as_phone_not_nid() -> None:
    """PRIV-001's metering half: these fell through to the Unicode-aware NID rule.

    ``_NID_RE`` uses ``\\d``, which matches Bangla digits, so the number was
    redacted -- but counted under ``kind="nid"``. The metering kind decides
    which disclosure a dashboard reports, so the classification matters.
    """
    for spelling in ("+8801712345678", "০১৭১২৩৪৫৬৭৮"):
        _, counts = redact_pii(spelling)
        assert counts == {"phone": 1, "email": 0, "nid": 0}, spelling


def test_phone_shaped_runs_that_are_not_mobiles_stay_out_of_the_phone_kind() -> None:
    """Boundaries: a digit glued to either side is a longer run, not a mobile.

    Nine-digit runs, eighteen-digit runs and the curricula numerals must never
    be counted as a phone disclosure.
    """
    cases = {
        "id 123456789 ok": {"phone": 0, "email": 0, "nid": 0},
        "id 123456789012345678 ok": {"phone": 0, "email": 0, "nid": 0},
        "ref 017123456789 end": {"phone": 0, "email": 0, "nid": 1},
        "১৯৪৭ সালে কি হয়েছিল?": {"phone": 0, "email": 0, "nid": 0},
        "৬ষ্ঠ শ্রেণির অধ্যায় ৩": {"phone": 0, "email": 0, "nid": 0},
    }
    for text, expected in cases.items():
        redacted, counts = redact_pii(text)
        assert counts == expected, redacted
        assert "[phone redacted]" not in redacted, redacted


def test_separated_phone_inside_a_question_leaves_the_question_intact() -> None:
    text, counts = redact_pii("আমার ফোন 01712-345678, ভগ্নাংশ কী?")
    assert counts == {"phone": 1, "email": 0, "nid": 0}, text
    assert "01712-345678" not in text
    assert "ভগ্নাংশ কী?" in text
    assert text == "আমার ফোন [phone redacted], ভগ্নাংশ কী?"


def test_evidence_prompt_meters_a_separated_phone_as_phone_kind() -> None:
    before = PII_REDACTED_TOTAL.labels(kind="phone")._value.get()
    prompt = build_evidence_prompt([], "আমার ফোন 01712-345678, ভগ্নাংশ কী?", history=None)
    assert "01712-345678" not in prompt
    assert "[phone redacted]" in prompt
    after = PII_REDACTED_TOTAL.labels(kind="phone")._value.get()
    assert after - before == 1


@pytest.mark.parametrize(
    "phone",
    [
        "+880 2 9661234",
        "02 9661234",
        "02-9661234",
        "+880 2 96612345",
        "031 619619",
        "০২-৯৬৬১২৩৪৫",
    ],
)
def test_bd_landline_numbers_are_redacted(phone: str) -> None:
    """A Dhaka/Chittagong-style landline is as much egress PII as a mobile:
    the mobile rule requires the 01[3-9] prefix and NID needs 10+ contiguous
    digits, so `+880 2 9661234` (9 separated digits) survived to egress."""
    text, counts = redact_pii(f"অফিস {phone} এ কল করুন")
    assert phone not in text, text
    assert "[phone redacted]" in text
    assert counts == {"phone": 1, "email": 0, "nid": 0}


def test_landline_redaction_leaves_curriculum_numerals_alone() -> None:
    for benign in [
        "maatham score 29661234 নয়",  # contiguous 8 digits: not a landline shape
        "৯৬৬১২৩৪ নম্বরটা কত",  # bare subscriber digits, no area code
        "১৯৭১ সালে ২টা ঘটনা",
    ]:
        text, counts = redact_pii(benign)
        assert redacted_total(counts) == 0, benign


def test_govt_report_scan_passes_iso_timestamps_in_every_year() -> None:
    """Audit re-check (2026-11-12): the claimed 2025-2027 timestamp
    allowlist time-bomb does not exist — an ISO `T`-separated token breaks
    the phone-shape scan before the year whitelist is ever consulted, for
    ANY year. Pin that: a future year must not start failing the export
    scan, and the token-level mechanism must not be "fixed" into something
    that also rescues phone-like digit runs."""

    from bangla_gpt_api.services.govt_report import pii_violations

    for year in (2026, 2028, 2031, 2040):
        stamp = f"{year}-06-30T09:15:30+06:00"
        assert pii_violations(stamp) == [], (year, stamp)


def test_govt_report_scan_flags_whitespace_timestamps_in_every_year() -> None:
    """The counter-shape: a whitespace-separated timestamp IS flagged (both
    years — behavior is NOT year-dependent; the scan fails closed loudly).
    Deliberately documented here as the operator-visible cost of treating
    digit runs as phone-shaped."""

    from bangla_gpt_api.services.govt_report import pii_violations

    for year in (2026, 2031):
        assert pii_violations(f"{year}-06-30 09:15:30") != [], year
