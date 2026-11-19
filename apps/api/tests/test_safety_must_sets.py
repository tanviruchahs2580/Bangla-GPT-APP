"""T-24: the must_allow / must_refuse case sets (tests/data/safety_cases.json).

The sets are measured here, red-first: a must_allow case the safety layer
blocks, or a must_refuse case that passes through, fails this module and is a
proven rule-level defect. Bangla strings reuse EXISTING repository text (the
safety module's own documented academic exception, the sample corpus topics,
the red-team set's minimal probes) — no authored Bangla (H-11), nothing
graphic. Output-side cases run through the fake provider's answer path via
the same screen the tutor uses (screen_question on the answer, tutor.py:1272).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bangla_gpt_api.services.safety import screen_question

CASES = json.loads(
    (Path(__file__).parent / "data" / "safety_cases.json").read_text(encoding="utf-8")
)


@pytest.mark.parametrize("case", CASES["must_allow"], ids=lambda c: c["category"])
def test_must_allow_passes_through(case):
    verdict = screen_question(case["text"])
    assert verdict.safe, (
        f"must_allow case blocked: category={case['category']} reason={verdict.reason!r}"
    )


@pytest.mark.parametrize("case", CASES["must_refuse"], ids=lambda c: c["category"])
def test_must_refuse_is_blocked(case):
    verdict = screen_question(case["text"])
    assert not verdict.safe, f"must_refuse case PASSED THROUGH: category={case['category']}"
