"""Golden set v3 -- construction, composition, split and leakage gates (F-051).

The defect this file guards against: v2 generated questions by lifting text out
of the index and keeping only items the system already handled, so 511/634
stems occurred verbatim in the corpus and the 1.00 metrics could not fail. v3
derives questions from curriculum constructs and emits every one of them.

These tests run against the committed artifact and the real bundled corpus, so
a hand-edit of `eval/golden_v3.json` that reintroduces lifted text, drops the
version field, empties a split or miscounts the composition fails here.
"""

from __future__ import annotations

import json
from pathlib import Path

from bangla_gpt_api.data.loader import load_sample_corpus
from bangla_gpt_api.evaluation import golden_v3
from bangla_gpt_api.evaluation.cli import _check_golden

API_ROOT = Path(__file__).resolve().parents[1]  # apps/api
GOLDEN_V3 = API_ROOT / "eval" / "golden_v3.json"


def _golden() -> dict:
    return json.loads(GOLDEN_V3.read_text(encoding="utf-8"))


def test_committed_golden_v3_passes_the_integrity_gate(capsys) -> None:
    assert _check_golden(GOLDEN_V3) == 0
    out = capsys.readouterr().out
    assert "GOLDEN SET: PASS" in out
    assert golden_v3.GOLDEN_V3_VERSION in out


def test_golden_v3_carries_a_version_and_a_split() -> None:
    data = _golden()
    assert data["version"] == golden_v3.GOLDEN_V3_VERSION
    assert data["bootstrap_seed"] == golden_v3.BOOTSTRAP_SEED
    splits = {item["split"] for item in data["items"]}
    assert splits == {"dev", "test"}
    # Do not tune on test: every item belongs to exactly one split, and roughly
    # a third of the set is the inspectable dev slice.
    dev = sum(1 for item in data["items"] if item["split"] == "dev")
    assert 0.25 <= dev / len(data["items"]) <= 0.4


def test_questions_are_constructs_not_lifted_index_text() -> None:
    """No question is a corpus span, and no prompt contains one (F-051/LLM-04)."""
    chunks = load_sample_corpus()
    data = _golden()
    report = golden_v3.leakage_report(data["items"], chunks, golden_v3.prompt_texts())
    assert report["violations"] == []
    # The construct phrase is the only corpus-visible run a question may share.
    assert report["max_non_construct_run"] < golden_v3.MAX_NON_CONSTRUCT_RUN
    # v2's failure mode measured 511/634 stems verbatim; on v3 it must be zero.
    squashed = [golden_v3._squash(chunk.text) for chunk in chunks]
    lifted = [
        item["question"]
        for item in data["items"]
        if golden_v3._squash(item["question"]) in squashed
    ]
    assert lifted == []


def test_leakage_gate_rejects_a_question_that_is_a_corpus_span() -> None:
    """A tampered item copied out of a chunk must fail the gate (rule bites)."""
    chunks = load_sample_corpus()
    data = _golden()
    lifted_question = chunks[0].text.split("\n")[0].strip()
    tampered = {**data}
    tampered["items"] = [
        {**data["items"][0], "question": f"{lifted_question} ব্যাখ্যা করো।", "construct": None},
        *data["items"][1:],
    ]
    problems = golden_v3.check_golden(tampered, chunks, golden_v3.prompt_texts())
    assert any("leakage" in problem for problem in problems)


def test_negative_tokens_are_absent_from_the_corpus() -> None:
    """expect="refuse" rests on corpus absence, not on observed system behaviour."""
    chunks = load_sample_corpus()
    assert golden_v3.absence_violations(_golden()["items"], chunks) == []


def test_generation_is_deterministic_and_covers_every_chapter() -> None:
    chunks = load_sample_corpus()
    first = golden_v3.build_items(chunks)
    second = golden_v3.build_items(chunks)
    assert [item["question"] for item in first] == [item["question"] for item in second]
    chapters = {chunk.meta.chapter for chunk in chunks if chunk.meta.chapter}
    covered = {item["chapter"] for item in first if item["expect"] == "answer"}
    assert covered == chapters


def test_generation_does_not_consult_the_retriever() -> None:
    """No item may be dropped or kept on system behaviour (v2's selection bug)."""
    chunks = load_sample_corpus()
    items = golden_v3.build_items(chunks)
    per_template = golden_v3.composition_report(items)["by_query_form"]
    # Every listed form appears; a form the system fails wholesale (banglish on
    # the pre-fix gate) still contributes items -- that is the point.
    assert set(per_template) >= {"bn", "bn_typo", "banglish", "mixed", "en"}


def test_split_assignment_is_deterministic_and_documented() -> None:
    assert golden_v3.split_of("প্রশ্ন", 6, "science") == golden_v3.split_of("প্রশ্ন", 6, "science")
    assert golden_v3.split_of("প্রশ্ন", 6, "science") in {"dev", "test"}


def test_composition_counts_match_the_items() -> None:
    data = _golden()
    assert data["composition"] == golden_v3.composition_report(data["items"])
    assert data["composition"]["total"] == len(data["items"])
    assert data["negatives"] == data["composition"]["by_expect"]["refuse"]


def test_typo_form_is_a_single_deterministic_edit() -> None:
    # A chapter with a vowel sign gets the sign confusion (same length);
    # one without gets the documented internal-character drop.
    swapped = golden_v3._typo("সন্ধি")
    assert swapped == "সন্ধী"
    dropped = golden_v3._typo("ভগ্নাংশ")
    assert dropped == "ভগনাংশ"
    for chapter in ("সন্ধি", "ভগ্নাংশ"):
        assert golden_v3._typo(chapter) == golden_v3._typo(chapter)
        assert golden_v3._typo(chapter) != chapter
