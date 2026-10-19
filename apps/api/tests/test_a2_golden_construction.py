"""Construction invariants of the golden set (AUD-A2-02 / A8-01).

The audit found the set self-fulfilling: its positives had been kept only
when the tutor's own coverage gate and the retrieval index already passed
them, so the gate could not measure a regression in either. These tests pin
the opposite construction:

* the generator does not consult the system under test (source-level guard --
  re-importing the tutor or index into it is the defect returning);
* the committed artifact carries provenance, strata, answerability labels and
  a frozen dev/test split whose hashes match a recomputation;
* the spec floors hold (>= 300 items, >= 250 positives).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
GENERATOR = REPO / "apps" / "api" / "scripts" / "gen_golden_v2.py"
GOLDEN = REPO / "apps" / "api" / "eval" / "golden_v2.json"

DATA = json.loads(GOLDEN.read_text(encoding="utf-8"))
ITEMS = DATA["items"]


def _hash(questions: list[str]) -> str:
    payload = "\n".join(sorted(questions)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def test_generator_does_not_consult_the_system_under_test() -> None:
    source = GENERATOR.read_text(encoding="utf-8")
    for forbidden in ("TutorService", "HybridIndex", "_gate_coverage", "index.search"):
        assert forbidden not in source, f"generator imports the system under test: {forbidden}"


def test_artifact_carries_provenance_and_split() -> None:
    assert DATA["generated_by"] == "scripts/gen_golden_v2.py"
    for item in ITEMS:
        assert item["split"] in {"dev", "test"}
        assert isinstance(item["synthetic"], bool) and item["synthetic"] is True
        assert item["answerability"] in {"in_corpus", "out_of_corpus"}
        assert item["stratum"]
        if item["expect"] == "answer":
            assert item["chapter"] and item["section"]
            assert item["answerability"] == "in_corpus"
        else:
            assert item["answerability"] == "out_of_corpus"


def test_spec_floors_hold() -> None:
    positives = [i for i in ITEMS if i["expect"] == "answer"]
    assert len(ITEMS) >= 300
    assert len(positives) >= 250
    assert DATA["counts"]["items"] == len(ITEMS)
    assert DATA["counts"]["positives"] == len(positives)


def test_split_hashes_match_a_recomputation() -> None:
    test_questions = [i["question"] for i in ITEMS if i["split"] == "test"]
    assert _hash([i["question"] for i in ITEMS]) == DATA["dataset_hash"]
    assert _hash(test_questions) == DATA["test_split_hash"]
    # Both sides of the split are populated; the held-out side is substantial.
    assert len(test_questions) >= 100
    assert DATA["counts"]["test"] == len(test_questions)


def test_positive_strata_are_both_present() -> None:
    strata = {i["stratum"] for i in ITEMS if i["expect"] == "answer"}
    assert {"definition", "contextual"} <= strata


def test_negative_strata_cover_the_required_families() -> None:
    strata = {i["stratum"] for i in ITEMS if i["expect"] == "refuse"}
    assert {"out_of_corpus", "english_world_fact", "gibberish", "personal_data"} <= strata


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__])
