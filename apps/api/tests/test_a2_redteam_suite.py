"""Structure and coverage of the red-team suite (AUD-A2-04).

The suite must exercise the attack classes the audit found missing
(markdown/image exfiltration, memory and history poisoning, goal hijack,
action abuse, encoding and translation tricks) in Bangla, Banglish and
English, at the spec floor of 40 cases -- and its construction contract must
hold on the committed artifact: ``token_absent`` items share no token with
the corpus (so refusal follows mechanically), ``natural`` items are realistic
phrasings whose refusal is verified by the eval CLI run itself, never
assumed.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from bangla_gpt_api.data.loader import load_sample_corpus
from bangla_gpt_api.retrieval.bm25 import tokenize

ROOT = Path(__file__).resolve().parents[3]  # repo root
SUITE = json.loads((ROOT / "apps" / "api" / "eval" / "redteam_v2.json").read_text(encoding="utf-8"))
ITEMS = SUITE["items"]

REQUIRED_CATEGORY_FRAGMENTS = (
    "override",
    "leak",
    "exfil",
    "tag_spoof",
    "memory",
    "history",
    "hijack",
    "action_abuse",
)


def test_suite_meets_the_spec_floor() -> None:
    assert len(ITEMS) >= 40, f"spec floor is 40 cases, found {len(ITEMS)}"


def test_every_item_expects_refusal_and_declares_construction() -> None:
    for item in ITEMS:
        assert item["expect"] == "refuse", item
        assert item.get("construction", "token_absent") in {"token_absent", "natural"}, item
        assert item["category"], item


def test_required_attack_classes_are_present() -> None:
    categories = {item["category"] for item in ITEMS}
    joined = " ".join(categories)
    for fragment in REQUIRED_CATEGORY_FRAGMENTS:
        assert fragment in joined, f"missing attack class: {fragment} (have {sorted(categories)})"


def test_all_three_input_scripts_are_present() -> None:
    joined = " ".join(item["question"] for item in ITEMS)
    assert re.search(r"[\u0980-\u09ff]", joined), "no Bangla item"
    assert re.search(r"[a-z]{3}", joined), "no Latin-script item"
    # Banglish: Latin script with Bangla function words (e.g. "tomar", "gulo").
    assert re.search(r"\b(tomar|tor|ami|ja|gulo|dao|koro)\b", joined), "no Banglish item"


def test_no_duplicate_questions() -> None:
    questions = [item["question"] for item in ITEMS]
    assert len(questions) == len(set(questions))


def test_token_absence_contract_holds_on_the_committed_artifact() -> None:
    """Re-verifies the generator's invariant without rewriting the file."""
    corpus: set[str] = set()
    for chunk in load_sample_corpus():
        corpus.update(tokenize(chunk.text))
    for item in ITEMS:
        if item.get("construction") == "natural":
            continue
        leaks = sorted({t for t in tokenize(item["question"]) if len(t) >= 2 and t in corpus})
        assert not leaks, f"{item['category']}: {leaks}"


def test_suite_records_its_rule_and_categories() -> None:
    assert "rule" in SUITE and "token_absent" in SUITE["rule"]
    assert set(SUITE.get("categories", [])) == {item["category"] for item in ITEMS}


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__])
