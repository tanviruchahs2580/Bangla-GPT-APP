"""Lexicon curation contracts (RAG audit F-12/B6).

The curated query maps are load-bearing for grounding: an entry that names a
term the corpus never carries manufactures evidence, and a phrase-shaped
entry silently matches nothing. These tests pin the curation rules, prove
both consumer modules share ONE versioned source of truth, and prove the
validator actually catches defects (a validator that never fires is dead
code, not a guardrail).
"""

from __future__ import annotations

from bangla_gpt_api.retrieval import lexicon
from bangla_gpt_api.retrieval.hybrid import QUERY_EXPANSIONS as HYBRID_EXPANSIONS
from bangla_gpt_api.retrieval.lexicon import (
    ENGLISH_BANGLA_GLOSSARY,
    LEXICON_VERSION,
    QUERY_EXPANSIONS,
    validate_lexicon,
)
from bangla_gpt_api.retrieval.query_analysis import ENGLISH_BANGLA_GLOSSARY as QA_GLOSSARY


def test_consumer_modules_share_one_lexicon() -> None:
    assert HYBRID_EXPANSIONS is QUERY_EXPANSIONS
    assert QA_GLOSSARY is ENGLISH_BANGLA_GLOSSARY
    assert LEXICON_VERSION


def test_current_lexicon_is_self_consistent() -> None:
    assert validate_lexicon() == []


def test_validator_catches_dead_and_phrase_entries() -> None:
    # 'দর্পণ ও প্রতিবিম্ব' breaks the key rule; the second entry breaks the
    # value rule the same way the three real phrase entries (algebra,
    # variable, circle) did before the validator forced their repair.
    broken = {**QUERY_EXPANSIONS, "পরীক্ষা": frozenset(), "দর্পণ": frozenset({"বীজগণিতীয় রাশি"})}
    original = lexicon.QUERY_EXPANSIONS
    lexicon.QUERY_EXPANSIONS = broken
    try:
        problems = validate_lexicon()
    finally:
        lexicon.QUERY_EXPANSIONS = original
    assert any("maps to nothing" in p for p in problems)
    assert any("phrase" in p for p in problems)


def test_validator_catches_script_mixing() -> None:
    original = lexicon.ENGLISH_BANGLA_GLOSSARY
    lexicon.ENGLISH_BANGLA_GLOSSARY = {**original, "কোষ": frozenset({"কোষ"})}
    try:
        problems = validate_lexicon()
    finally:
        lexicon.ENGLISH_BANGLA_GLOSSARY = original
    assert any("English/Banglish surface form" in p for p in problems)


def test_glossary_covers_the_audit_report_examples() -> None:
    # The cross-script lanes the grounding gate relies on are contractually
    # load-bearing: a curation edit that drops 'cell' or 'hypotenuse' must
    # be a visible, reviewed change — not a silent simplification. Sets are
    # compared because tuple(frozenset) order is process-dependent.
    assert english_gloss("cell") == ("কোষ",)
    assert set(english_gloss("hypotenuse")) == {"অতিভুজ", "ত্রিভুজ"}
    assert "ভগ্নাংশ" in QUERY_EXPANSIONS


def english_gloss(token: str) -> tuple[str, ...]:
    from bangla_gpt_api.retrieval.query_analysis import english_gloss_terms

    return tuple(english_gloss_terms(token))
