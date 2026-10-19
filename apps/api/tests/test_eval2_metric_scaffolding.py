"""The golden gate's metric layer must not move when prompt scaffolding is added.

A5-01 added `[id=<chunk> | class 6 › science › chapter › section]` headers to
the evidence passages the model sees. The mock provider quotes evidence
verbatim, so those header lines came back as answer "sentences" that match no
source excerpt: faithfulness fell 0.855 -> 0.458 and grammar 0.988 -> 0.797 in
the working tree. Stripping the header (app-added scaffolding, like the mock
marker and bullets) restores the metric to measuring the answer text. These
tests pin both directions: scaffolding is stripped, content is not.
"""

from __future__ import annotations

from bangla_gpt_api.evaluation.metrics import (
    _overlap_fraction,
    grammar_score,
    normalize_sentence,
    split_sentences,
)

HEADER = "[id=e0365cc2b0a935ed | class 6 › science › কোষ › কোষের প্রধান অংশ]"


def test_passage_header_lines_normalize_to_nothing() -> None:
    assert normalize_sentence(HEADER) == ""
    assert normalize_sentence(f"- {HEADER}") == ""
    assert normalize_sentence(f"[mock] সহজ ব্যাখ্যা: {HEADER}") == ""
    assert normalize_sentence(f"সহজ ব্যাখ্যা: {HEADER} কোষ হলো জীবদেহের একক") == "কোষ হলো জীবদেহের একক"


def test_header_does_not_collide_with_content_that_merely_starts_with_bracket() -> None:
    # content that legitimately starts with "[" but is not a passage header
    line = "[পরিশিষ্ট] কোষ হলো জীবদেহের একক"
    assert normalize_sentence(line) == line
    assert normalize_sentence("[id=abc]") == "", "a bare header carries no content"


def test_grammar_ignores_scaffolding_but_not_content() -> None:
    content = "কোষ হলো জীবদেহের ক্ষুদ্রতম গঠনগত ও কার্যগত একক।"
    with_header = f"{HEADER}\n{content}"
    assert grammar_score(with_header) == grammar_score(content)
    assert grammar_score(f"{HEADER}\n{HEADER}") == 0.0, "header-only answers have no content"


def test_overlap_counts_a_quoted_header_answer_as_covered() -> None:
    content = "কোষ হলো জীবদেহের ক্ষুদ্রতম গঠনগত ও কার্যগত একক।"
    evidence = [content]
    answer = f"[mock] সহজ ব্যাখ্যা: {HEADER}\nউদাহরণ: {content}"
    assert _overlap_fraction(answer, evidence) == 1.0
    # sanity: the pre-existing scaffolding rules still hold. The splitter drops
    # the danda, which is why the overlap check matches the danda-free answer
    # sentence as a substring of the evidence text.
    assert split_sentences(f"{content}\n{content}") == [
        content.rstrip("।"),
        content.rstrip("।"),
    ]
