"""Unit tests for the RAG V5 index build CLI (offline tooling).

The CLI turns the normalized corpus into a pgvector generation: digest →
create_building → batch embed+upsert → validate → mark_validated. The
integration path (real Postgres + the real 847-chunk corpus) is exercised
against the staging lane and recorded in the wave report; these tests pin
the pure logic so the CLI cannot silently drift.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

# The CLI lives in scripts/ (operator tooling, not an installed package),
# so load it by path — a bare `pytest` run in CI has no cwd on sys.path.
_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_index_generation.py"
_spec = importlib.util.spec_from_file_location("build_index_generation", _SCRIPT)
_mod = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
# dataclass resolution reads sys.modules for the module's __module__, so the
# module must be registered before it executes.
sys.modules["build_index_generation"] = _mod
_spec.loader.exec_module(_mod)

chunk_rows = _mod.chunk_rows
corpus_digest = _mod.corpus_digest
load_chunks = _mod.load_chunks
validate_database_url = _mod.validate_database_url


def _write_corpus(tmp_path: Path, sources: dict[str, list[dict]]) -> Path:
    manifest = {
        "sources": [
            {
                "source_id": sid,
                "subject_bn": "পদার্থবিদ্যা" if sid.startswith("hsc") else "বিজ্ঞান",
                "level": "hsc" if sid.startswith("hsc") else "secondary",
                "normalized_sha256": "x" * 64,
                "chunks": len(rows),
            }
            for sid, rows in sources.items()
        ]
    }
    (tmp_path / "manifests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "manifests" / "corpus_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    normalized = tmp_path / "normalized"
    normalized.mkdir()
    for sid, rows in sources.items():
        with open(normalized / f"{sid}.chunks.jsonl", "w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return tmp_path


def test_corpus_digest_is_stable_and_text_sensitive(tmp_path: Path) -> None:
    data = _write_corpus(
        tmp_path,
        {
            "s1": [
                {"chunk_id": "a", "text": "প্রথম অংশ"},
                {"chunk_id": "b", "text": "দ্বিতীয় অংশ"},
            ],
            "s2": [{"chunk_id": "c", "text": "তৃতীয় অংশ"}],
        },
    )
    chunks = load_chunks(data)
    d1 = corpus_digest(chunks)
    d2 = corpus_digest(load_chunks(data))
    assert d1 == d2 and len(d1) == 64

    changed = _write_corpus(
        tmp_path / "other",
        {
            "s1": [
                {"chunk_id": "a", "text": "প্রথম অংশ"},
                {"chunk_id": "b", "text": "বদলে যাওয়া অংশ"},
            ],
            "s2": [{"chunk_id": "c", "text": "তৃতীয় অংশ"}],
        },
    )
    assert corpus_digest(load_chunks(changed)) != d1


def test_load_chunks_carries_manifest_metadata(tmp_path: Path) -> Path:
    data = _write_corpus(
        tmp_path,
        {
            "hsc-1": [{"chunk_id": "a", "text": "লেখা", "chapter": "গতি"}],
            "sec-1": [{"chunk_id": "b", "text": "লেখা ২", "detected_class": 6}],
        },
    )
    chunks = load_chunks(data)
    by_id = {c.chunk_id: c for c in chunks}
    assert by_id["a"].source_id == "hsc-1"
    assert by_id["a"].subject == "পদার্থবিদ্যা"
    assert by_id["a"].chapter == "গতি"
    assert by_id["b"].class_level == 6
    return data


def test_chunk_rows_embeds_with_the_configured_embedder(tmp_path: Path) -> None:
    from bangla_gpt_api.retrieval.embedding import HashingEmbedder

    data = _write_corpus(
        tmp_path,
        {"s1": [{"chunk_id": "a", "text": "ভগ্নাংশের সংজ্ঞা"}]},
    )
    embedder = HashingEmbedder()
    rows = chunk_rows(load_chunks(data), embedder)
    assert len(rows) == 1
    chunk_id, source_id, class_level, subject, chapter, vec = rows[0]
    assert chunk_id == "a" and source_id == "s1"
    assert len(vec) == embedder.dim
    assert all(v == v for v in vec)  # finite
    assert class_level is None and chapter is None


def test_validate_database_url_refuses_sqlite() -> None:
    with pytest.raises(SystemExit):
        validate_database_url("sqlite:///./bangla_gpt.db")
    validate_database_url("postgresql+psycopg://u:p@localhost:5433/db")
