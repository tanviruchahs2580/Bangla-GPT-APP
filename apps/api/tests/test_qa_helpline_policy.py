"""Helpline policy guard (F-001).

The 2026-10-29 audit found the self-harm refusal copy naming a mental-health
line ("09666-777222") that no official source carries: the Directorate General
of Health Services' hotline pages (https://www.dghs.gov.bd, retrieved
2026-10-29) list 16263 (health call centre, 24/7), 999 (national emergency),
333 and 102 - and not that number. For a children's product, showing an
unverifiable crisis number is a defect in itself, so the copy now carries only
DGHS-documented services.

This test is the regression guard: it fails if anyone edits the refusal copy to
contain a phone-number-shaped string that is not in `SAFE_HELPLINES`. The
allowlist may only grow with a source URL and a retrieval date in the comment
above it.
"""

import re

from bangla_gpt_api.services.safety import (
    HELPLINE_EMERGENCY,
    HELPLINE_HEALTH_CALL_CENTRE,
    SAFE_HELPLINES,
    SELF_HARM_ANSWER,
    UNSAFE_ANSWER_REFUSAL,
    refusal_for,
)

# Bangla and Latin digits in phone-number-shaped runs of 3+ digits with
# optional separators, which is what every national helpline looks like in
# either script (999, 333, 102, 16263). Two-digit runs are deliberately not
# matched: the same copy legitimately says "(২৪ ঘণ্টা)" - 24 hours.
NUMBER_SHAPED = re.compile(r"[০-৯0-9][০-৯0-9\-–\s]{1,}[০-৯0-9]")


def _numbers_in(text: str) -> set[str]:
    found = set()
    for match in NUMBER_SHAPED.finditer(text):
        digits = re.sub(r"[^০-৯0-9]", "", match.group(0))
        found.add(digits)
    return found


def test_self_harm_copy_names_only_verified_helplines() -> None:
    copy = refusal_for("self_harm")
    assert copy == SELF_HARM_ANSWER
    # Both documented services are present, in the copy the child actually sees.
    assert HELPLINE_HEALTH_CALL_CENTRE in copy
    assert HELPLINE_EMERGENCY in copy
    # And nothing else number-shaped: an unverified number cannot ship again
    # without being added to SAFE_HELPLINES with its source.
    allowed_digits = {re.sub(r"[^০-৯0-9]", "", n) for n in SAFE_HELPLINES}
    assert _numbers_in(copy) == allowed_digits, (
        f"refusal copy carries unverified numbers: {_numbers_in(copy) - allowed_digits}"
    )


def test_self_harm_copy_keeps_the_trusted_adult_path() -> None:
    # The human route stays first: the helplines complement it, never replace it.
    assert "বড় মানুষ" in SELF_HARM_ANSWER
    assert "শিক্ষক" in SELF_HARM_ANSWER


def test_allowlist_entries_are_documented_services() -> None:
    # A bare allowlist is a loophole; each entry must be one of the constants
    # whose comment carries the source and the retrieval date.
    assert set(SAFE_HELPLINES) == {HELPLINE_HEALTH_CALL_CENTRE, HELPLINE_EMERGENCY}


def test_other_refusal_copy_stays_number_free() -> None:
    # Only the self-harm path may carry contact numbers; every other refusal
    # stays free of them so no unverified number leaks through another path.
    assert not _numbers_in(UNSAFE_ANSWER_REFUSAL)
    assert not _numbers_in(refusal_for("prompt_injection"))
    assert not _numbers_in(refusal_for("sexual_content"))
