"""AUD-A1-16/A1-17/A1-18/A1-19/A1-23: ledger rights, tunables, diagram, langid.

* the licence ledger carries a per-document permission status, not one
  boilerplate string shared by every artifact;
* the retrieval tunables are tabulated in docs/RAG_ARCHITECTURE.md with
  their in-code values (a drift guard, so the register cannot rot);
* the as-built data-flow diagram is a Mermaid flowchart whose file
  references all exist;
* script/language detection is an explicit module with Banglish coverage.
"""

from __future__ import annotations

import re
from pathlib import Path

from bangla_gpt_api.nctb.manifest import SourceRecord
from bangla_gpt_api.retrieval.langid import classify_query, is_banglish, script_of

REPO_ROOT = Path(__file__).resolve().parents[3]
RAG_DOC = REPO_ROOT / "docs" / "RAG_ARCHITECTURE.md"


def test_source_record_carries_permission_status() -> None:
    record = SourceRecord(
        source_id="src-a",
        source_url="https://example.invalid/a.pdf",
        parent_url="https://example.invalid/list",
        retrieved_at="2026-10-18T00:00:00+00:00",
        content_hash="0" * 64,
        file_name="a.pdf",
        file_type="application/pdf",
        file_size=10,
        level="secondary",
        subject_bn="বাংলা",
        book="বাংলা",
        curriculum_year="2012",
        edition="প্রকাশকাল ২০১২",
    )
    assert record.permission_status == "official-public-download"
    assert record.redistribution == "not-granted-in-writing"
    assert "permission_status" in record.to_json()


def test_tunables_register_matches_the_code() -> None:
    """Each register row must name the live value — a doc-vs-code drift guard."""
    doc = RAG_DOC.read_text(encoding="utf-8")
    register = doc.split("## Tunables register", 1)
    assert len(register) == 2, "docs/RAG_ARCHITECTURE.md must carry a Tunables register section"
    section = register[1].split("\n## ", 1)[0]

    from bangla_gpt_api.nctb.chunking import MAX_WORDS, MIN_WORDS, TARGET_WORDS
    from bangla_gpt_api.nctb.content_qa import DEFAULT_FLAGGED_THRESHOLD
    from bangla_gpt_api.retrieval.bm25 import _TRIGRAM_WEIGHT
    from bangla_gpt_api.retrieval.diversity import DEFAULT_LAMBDA
    from bangla_gpt_api.retrieval.hybrid import _MIN_STEM_LEN, QUERY_EXPANSIONS
    from bangla_gpt_api.retrieval.hybrid_index import (
        _PROXIMITY_WINDOW,
        _RRF_K,
        _W_COVERAGE,
        _W_PROXIMITY,
        _W_RRF,
        _W_TRIGRAM,
    )

    expected = {
        "TARGET_WORDS": str(TARGET_WORDS),
        "MIN_WORDS": str(MIN_WORDS),
        "MAX_WORDS": str(MAX_WORDS),
        "DEFAULT_FLAGGED_THRESHOLD": str(DEFAULT_FLAGGED_THRESHOLD),
        "DEFAULT_LAMBDA": str(DEFAULT_LAMBDA),
        "k1": "1.5",
        "b": "0.75",
        "_RRF_K": str(_RRF_K),
        "_W_RRF": str(_W_RRF),
        "_W_COVERAGE": str(_W_COVERAGE),
        "_W_PROXIMITY": str(_W_PROXIMITY),
        "_W_TRIGRAM": str(_W_TRIGRAM),
        "_PROXIMITY_WINDOW": str(_PROXIMITY_WINDOW),
        "_TRIGRAM_WEIGHT": str(_TRIGRAM_WEIGHT),
        "_MIN_STEM_LEN": str(_MIN_STEM_LEN),
    }
    for name, value in expected.items():
        row = f"`{name}`"
        assert row in section, f"register is missing {row}"
        line = next(line for line in section.splitlines() if row in line)
        assert value in line, f"register row for {name} does not show the live value {value}"
    assert "QUERY_EXPANSIONS" in section
    assert str(len(QUERY_EXPANSIONS)) in section


def test_as_built_diagram_is_mermaid_with_existing_file_references() -> None:
    doc = RAG_DOC.read_text(encoding="utf-8")
    assert "```mermaid" in doc, "the as-built diagram must be Mermaid"
    block = doc.split("```mermaid", 1)[1].split("```", 1)[0]
    references = set(re.findall(r"bangla_gpt_api/[\w/]+\.py", block))
    assert len(references) >= 8, f"diagram must cite per-box files, found {sorted(references)}"
    for reference in references:
        path = REPO_ROOT / "apps" / "api" / "src" / reference
        assert path.exists(), f"diagram cites a file that does not exist: {reference}"
    for symbol in ("search(", "reciprocal_rank_fusion", "CachedRankingIndex"):
        assert symbol in block, f"as-built diagram must name the real step {symbol}"


def test_script_detection_is_explicit() -> None:
    assert script_of("ভগ্নাংশ কী?") == "bangla"
    assert script_of("bhognangsho ki?") == "latin"
    assert script_of("ভগ্নাংশ fraction 2") == "mixed"
    assert script_of("১২৩ 456") in {"none", "other"}
    assert classify_query("ভগ্নাংশ কী?") == "bangla"
    assert classify_query("kosh ki? kosh er bhitore ki thake", roman_matches=["কোষ"]) == "banglish"
    assert classify_query("what is a cell?") == "english"
    assert is_banglish("kosh ki", roman_matches=["কোষ"])
    assert not is_banglish("what is a cell?", roman_matches=[])


def test_banglish_detection_does_not_claim_plain_english() -> None:
    # "distribute" is a real English word; the cluster heuristic must leave it alone
    assert classify_query("distribute the marks") == "english"
