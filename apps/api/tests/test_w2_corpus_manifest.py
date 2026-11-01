"""The corpus manifest, its check CLI and the startup verification (F-011/F-047/RAG-11).

The defect: no committed artifact could be tied to the pipeline that produced
it, and nothing rebuilt the tracked reports. The fix is a tracked manifest
(source hashes, tool fingerprint, artifact digests) plus a CLI that fails when
the tracked reports and the manifest disagree; these tests exercise both, on
a synthetic corpus and without the real PDFs.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest

from bangla_gpt_api.data.nctb_loader import load_nctb_corpus
from bangla_gpt_api.nctb.chunking import chunk_pages
from bangla_gpt_api.nctb.extract import PageText
from bangla_gpt_api.nctb.manifest import CORPUS_MANIFEST_NAME, verify_corpus_manifest
from bangla_gpt_api.providers.base import ProviderNotConfigured
from bangla_gpt_api.retrieval.embedding import HashingEmbedder, build_embedder

HERE = Path(__file__).resolve().parent
API_ROOT = HERE.parent
CHECK_SCRIPT = API_ROOT / "scripts" / "check_corpus_manifest.py"
EVAL_SCRIPT = API_ROOT / "scripts" / "evaluate_nctb_retrieval.py"

BODY = "কোষ হলো জীবদেহের ক্ষুদ্রতম গঠনগত ও কার্যগত একক। " * 25


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_corpus(root: Path) -> dict:
    """A one-source corpus with every artifact the manifest describes."""
    from bangla_gpt_api.nctb.manifest import SourceRecord, append_record

    extracted = root / "extracted"
    normalized = root / "normalized"
    extracted.mkdir(parents=True, exist_ok=True)
    normalized.mkdir(parents=True, exist_ok=True)
    pages = [PageText(1, "অধ্যায়: কোষ\n" + BODY)]
    (extracted / "src1.pages.json").write_text(
        json.dumps(
            {"source_id": "src1", "pages": [asdict(page) for page in pages]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    chunks = chunk_pages(pages, source_id="src1")
    with (normalized / "src1.chunks.jsonl").open("w", encoding="utf-8") as handle:
        for chunk in chunks:
            handle.write(json.dumps(asdict(chunk), ensure_ascii=False) + "\n")
    report = {
        "src1": {
            "level": "secondary",
            "subject_bn": "বিজ্ঞান শাখার বিষয়সমূহ",
            "curriculum_year": "2012",
            "bangla_char_ratio_on_usable": 1.0,
            "chunks": len(chunks),
            "chunks_with_chapter": sum(1 for chunk in chunks if chunk.chapter),
            "chapter_coverage": 1.0,
            "total_pages": 1,
            "usable_pages": 1,
        }
    }
    (root / "quality_report.json").write_text(
        json.dumps(report, ensure_ascii=False), encoding="utf-8"
    )

    manifests = root / "manifests"
    manifests.mkdir(exist_ok=True)
    record = SourceRecord(
        source_id="src1",
        source_url="https://example.invalid/src1.pdf",
        parent_url="https://example.invalid/listing",
        retrieved_at="2026-10-29T00:00:00+00:00",
        content_hash="a" * 64,
        file_name="src1.pdf",
        file_type="application/pdf",
        file_size=1234,
        level="secondary",
        subject_bn="বিজ্ঞান শাখার বিষয়সমূহ",
        book="বিজ্ঞান শাখার বিষয়সমূহ",
        curriculum_year="2012",
        edition="প্রকাশকাল ২০১২",
        source_status="acquired",
    )
    acquisition = manifests / "acquisition_manifest.jsonl"
    if acquisition.exists():
        acquisition.unlink()
    append_record(acquisition, record)
    return record


def _build_manifest(root: Path) -> dict:
    from bangla_gpt_api.nctb.corpus import (
        build_corpus_manifest,
        load_manifest,
        record_cross_source_report,
    )

    record_cross_source_report(root / "quality_report.json", root / "normalized")
    records = load_manifest(root / "manifests" / "acquisition_manifest.jsonl")
    return build_corpus_manifest(
        root,
        records,
        report_path=root / "quality_report.json",
        extracted_dir=root / "extracted",
        normalized_dir=root / "normalized",
    )


def _finalize_with_eval(root: Path, manifest: dict) -> dict:
    """Run the eval script's manifest finalizer with a stub report."""
    module = _load_module(EVAL_SCRIPT, "evaluate_nctb_retrieval")
    index_chunks = len(
        load_nctb_corpus(
            root / "normalized",
            quality_report_path=root / "quality_report.json",
            verify_manifest=False,
        )
    )
    report = {
        "corpus_chunks": index_chunks,
        "index_id_hash": "0" * 64,
        "evaluated_at": "2026-10-29T00:00:00+00:00",
    }
    (root / "retrieval_eval.json").write_text(
        json.dumps({"corpus_chunks": index_chunks}, ensure_ascii=False), encoding="utf-8"
    )
    module._update_manifest(root, report, embedder=HashingEmbedder())
    return json.loads((root / "manifests" / CORPUS_MANIFEST_NAME).read_text(encoding="utf-8"))


def _run_check(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CHECK_SCRIPT), *args],
        cwd=API_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
    )


class TestManifestShape:
    def test_manifest_records_tool_fingerprint_and_digests(self, tmp_path: Path) -> None:
        _write_corpus(tmp_path)
        manifest = _build_manifest(tmp_path)
        assert manifest["manifest_version"] == 1
        assert manifest["pipeline"]["code_fingerprint"].startswith("sha256:")
        assert manifest["pipeline"]["extractor"].startswith("pypdf-")
        assert manifest["edition"]["secondary"]
        assert manifest["edition"]["hsc"] == "UNKNOWN"
        assert manifest["totals"]["chunks"] == manifest["sources"][0]["chunks"]
        assert manifest["sources"][0]["normalized_sha256"]
        assert manifest["sources"][0]["extracted_sha256"]
        assert manifest["cross_source"]["total_chunks"] == manifest["totals"]["chunks"]

    def test_verification_passes_on_the_built_corpus(self, tmp_path: Path) -> None:
        _write_corpus(tmp_path)
        manifest = _build_manifest(tmp_path)
        final = _finalize_with_eval(tmp_path, manifest)
        loaded, problems = verify_corpus_manifest(tmp_path, index_chunks=5)
        assert loaded is not None
        assert problems == [], problems
        assert final["derived"]["index_chunks"] == 5

    def test_verification_reports_a_hand_edited_chunk_file(self, tmp_path: Path) -> None:
        _write_corpus(tmp_path)
        _build_manifest(tmp_path)
        chunk_file = tmp_path / "normalized" / "src1.chunks.jsonl"
        chunk_file.write_text(
            chunk_file.read_text(encoding="utf-8").replace("কোষ", "কোশ", 1), encoding="utf-8"
        )
        _manifest, problems = verify_corpus_manifest(tmp_path)
        assert any("digest differs" in problem for problem in problems), problems

    def test_missing_manifest_is_reported(self, tmp_path: Path) -> None:
        _manifest, problems = verify_corpus_manifest(tmp_path)
        assert problems and "no corpus manifest" in problems[0]


class TestCheckCli:
    def test_check_passes_on_a_consistent_corpus(self, tmp_path: Path) -> None:
        _write_corpus(tmp_path)
        manifest = _build_manifest(tmp_path)
        _finalize_with_eval(tmp_path, manifest)
        result = _run_check("--data-dir", str(tmp_path))
        assert result.returncode == 0, result.stdout + result.stderr
        assert "OK" in result.stdout

    def test_check_fails_when_the_report_disagrees_with_the_manifest(self, tmp_path: Path) -> None:
        _write_corpus(tmp_path)
        manifest = _build_manifest(tmp_path)
        _finalize_with_eval(tmp_path, manifest)
        report_path = tmp_path / "quality_report.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report["src1"]["chunks"] = report["src1"]["chunks"] + 1
        report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
        result = _run_check("--data-dir", str(tmp_path))
        assert result.returncode == 1
        assert "quality_report.json digest differs" in result.stdout

    def test_check_fails_when_the_acquisition_ledger_changed(self, tmp_path: Path) -> None:
        _write_corpus(tmp_path)
        manifest = _build_manifest(tmp_path)
        _finalize_with_eval(tmp_path, manifest)
        acquisition = tmp_path / "manifests" / "acquisition_manifest.jsonl"
        line = json.loads(acquisition.read_text(encoding="utf-8").splitlines()[0])
        line["content_hash"] = "b" * 64
        acquisition.write_text(json.dumps(line, ensure_ascii=False) + "\n", encoding="utf-8")
        result = _run_check("--data-dir", str(tmp_path))
        assert result.returncode == 1
        assert "content_hash" in result.stdout


class TestStartupVerification:
    def test_loader_logs_a_manifest_mismatch(self, tmp_path: Path, caplog) -> None:
        _write_corpus(tmp_path)
        manifest = _build_manifest(tmp_path)
        manifest["sources"][0]["normalized_sha256"] = "0" * 64
        (tmp_path / "manifests" / CORPUS_MANIFEST_NAME).write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
        )
        with caplog.at_level("ERROR"):
            chunks = load_nctb_corpus(
                tmp_path / "normalized", quality_report_path=tmp_path / "quality_report.json"
            )
        assert chunks
        assert "corpus manifest mismatch" in caplog.text

    def test_loader_warns_when_the_corpus_has_no_manifest(self, tmp_path: Path, caplog) -> None:
        _write_corpus(tmp_path)
        with caplog.at_level("WARNING"):
            load_nctb_corpus(
                tmp_path / "normalized", quality_report_path=tmp_path / "quality_report.json"
            )
        assert "carries no corpus manifest" in caplog.text

    def test_loader_logs_the_corpus_identity(self, tmp_path: Path, caplog) -> None:
        _write_corpus(tmp_path)
        _build_manifest(tmp_path)
        with caplog.at_level("INFO"):
            load_nctb_corpus(
                tmp_path / "normalized",
                quality_report_path=tmp_path / "quality_report.json",
                verify_manifest=False,
            )
        assert "nctb_corpus_identity" in caplog.text


class TestEmbedderIdentity:
    def _settings(self, corpus_dir: Path) -> SimpleNamespace:
        return SimpleNamespace(embedding_model="", nctb_corpus_dir=str(corpus_dir))

    def test_matching_embedder_passes(self, tmp_path: Path) -> None:
        _write_corpus(tmp_path)
        manifest = _build_manifest(tmp_path)
        manifest["derived"]["embedder"] = {"name": "hash-ngram-local", "dim": 384}
        (tmp_path / "manifests" / CORPUS_MANIFEST_NAME).write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
        )
        embedder = build_embedder(self._settings(tmp_path))
        assert embedder.name == "hash-ngram-local"

    def test_different_embedder_refuses_to_serve(self, tmp_path: Path) -> None:
        _write_corpus(tmp_path)
        manifest = _build_manifest(tmp_path)
        manifest["derived"]["embedder"] = {"name": "bge-m3", "dim": 1024}
        (tmp_path / "manifests" / CORPUS_MANIFEST_NAME).write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
        )
        with pytest.raises(ProviderNotConfigured, match="embedder"):
            build_embedder(self._settings(tmp_path))

    def test_no_corpus_dir_is_not_a_configuration_error(self) -> None:
        settings = SimpleNamespace(embedding_model="", nctb_corpus_dir="")
        assert build_embedder(settings).name == "hash-ngram-local"
