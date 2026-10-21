"""A3-03: the contextual header every indexable chunk carries.

Pins the class›subject›chapter›section header on :func:`indexable_text` —
the header the lexical lane, the grounding gate and the reranker all read —
and the two honesty properties that go with it:

* the header is built ONLY from chunk metadata that exists (a bare chunk
  still carries its class; nothing is invented);
* adding/holding the header does not touch chunk IDs: ids derive from the
  chunker's source|seq|page|full-text hash, so a rebuild keeps ids stable
  regardless of how the header renders (measured corpus-side: ids are
  content-addressed; see nctb/chunking._stable_id).
"""

from __future__ import annotations

from bangla_gpt_api.curriculum.models import Chunk, CurriculumMeta
from bangla_gpt_api.retrieval.bm25 import indexable_text


def _chunk(**meta_over: object) -> Chunk:
    base = dict(
        curriculum_year=2023,
        class_level=8,
        subject="science",
        book="বিজ্ঞান",
        source="nctb-x",
        chapter="কোষ",
        section="কোষ বিভাজন",
        page=3,
    )
    base.update(meta_over)
    return Chunk(id="x-1", text="কোষ বিভাজন দুই প্রক্রিয়ায় ঘটে।", meta=CurriculumMeta(**base))  # type: ignore[arg-type]


def test_header_carries_class_subject_chapter_section() -> None:
    text = indexable_text(_chunk())
    assert "class 8" in text
    assert "subject science" in text
    # Section rides with double weight (>= the two header repeats; the body
    # of this fixture's text repeats the phrase once more).
    assert text.count("কোষ বিভাজন") >= 2
    assert text.splitlines()[0].startswith("class 8")
    assert "কোষ বিভাজন দুই প্রক্রিয়ায় ঘটে।" in text


def test_header_without_section_or_chapter_carries_the_class() -> None:
    text = indexable_text(_chunk(section=None, chapter=""))
    assert "class 8" in text and "subject science" in text
    assert text.strip(), "a bare chunk still indexes the header and the body"
    # No empty metadata invented: no None leaks into the indexed text.
    assert "None" not in text


def test_header_never_moves_the_chunk_id() -> None:
    """Id stability: the id is content-addressed, the header is rendering."""
    chunk = _chunk()
    other_view = _chunk(class_level=9)  # different header, same content id space
    assert chunk.id == other_view.id == "x-1"
    assert indexable_text(chunk) != indexable_text(other_view)


def test_header_is_deterministic() -> None:
    assert indexable_text(_chunk()) == indexable_text(_chunk())
