"""Tests for the NCTB acquisition/processing pipeline (no network access)."""

import json
from dataclasses import asdict, replace
from pathlib import Path

from bangla_gpt_api.curriculum.models import Chunk
from bangla_gpt_api.data.nctb_loader import LEVEL_CLASS_RANGE, load_nctb_corpus
from bangla_gpt_api.nctb.acquisition import acquire_artifact
from bangla_gpt_api.nctb.chunking import chunk_pages
from bangla_gpt_api.nctb.extract import PageText, qc_pages
from bangla_gpt_api.nctb.manifest import load_manifest
from bangla_gpt_api.nctb.normalize import (
    bangla_char_ratio,
    detect_class_level,
    looks_like_garbage,
    normalize_bangla,
)
from bangla_gpt_api.nctb.sources import NctbArtifact, find_artifact

BANGLA_CELL = "কোষ হলো জীবদেহের ক্ষুদ্রতম গঠনগত ও কার্যগত একক।"


def _fake_fetcher(body: bytes = b"%PDF-1.4 fake", content_type: str = "application/pdf"):
    calls = []

    def fetch(url: str, **_):
        calls.append(url)
        return body, content_type

    fetch.calls = calls  # type: ignore[attr-defined]
    return fetch


ARTIFACT = NctbArtifact(
    file_id="abcdef1234567890abcdef1234567890",
    subject_bn="পদার্থবিদ্যা",
    level="hsc",
    parent_page="https://nctb.gov.bd/pages/files/x",
    storage_url=("https://objectstorage.example.com/abcdef1234567890abcdef1234567890.pdf"),
)


class TestNormalize:
    def test_nfc_and_zero_width_removal(self) -> None:
        out = normalize_bangla("কো\u200dষ কী?\u200b")
        assert "\u200b" not in out and "\u200d" not in out

    def test_whitespace_collapses(self) -> None:
        assert normalize_bangla("  a   b \n c ") == "a b c"

    def test_ascii_digits_option(self) -> None:
        assert normalize_bangla("শ্রেণি ৬", ascii_digits=True) == "শ্রেণি 6"

    def test_bangla_ratio(self) -> None:
        assert bangla_char_ratio("কোষ বিজ্ঞান") == 1.0
        mixed = bangla_char_ratio("photosynthesis সালোকসংশ্লেষণ")
        assert 0 < mixed < 1

    def test_garbage_detection(self) -> None:
        assert looks_like_garbage("")
        assert looks_like_garbage("abc\ufffd\ufffd\ufffd\ufffd")
        assert not looks_like_garbage("কোষ জীবনের একক")

    def test_detect_class_level_single(self) -> None:
        text = "জাতীয় শিক্ষাক্রম ও পাঠ্যপুস্তক বোর্ড\nষষ্ঠ শ্রেণি\nবিজ্ঞান"
        assert detect_class_level(text) == 6

    def test_detect_class_level_multi_is_none(self) -> None:
        assert detect_class_level("ষষ্ঠ শ্রেণি ও সপ্তম শ্রেণি") is None

    def test_detect_class_level_absent(self) -> None:
        assert detect_class_level("কোনো শ্রেণির উল্লেখ নেই") is None


class TestAcquisition:
    def test_acquire_then_resume_skips_download(self, tmp_path: Path) -> None:
        raw_dir = tmp_path / "raw"
        manifest_path = tmp_path / "manifests" / "m.jsonl"
        fetcher = _fake_fetcher()

        first = acquire_artifact(ARTIFACT, raw_dir, manifest_path, delay_seconds=0, fetcher=fetcher)
        assert first.source_status == "acquired"
        assert (raw_dir / f"{ARTIFACT.source_id}.pdf").exists()
        assert len(fetcher.calls) == 1

        second = acquire_artifact(
            ARTIFACT, raw_dir, manifest_path, delay_seconds=0, fetcher=fetcher
        )
        assert second.source_status == "acquired"
        assert len(fetcher.calls) == 1  # resumed: no re-download

    def test_content_type_validation(self, tmp_path: Path) -> None:
        record = acquire_artifact(
            ARTIFACT,
            tmp_path / "raw",
            tmp_path / "m.jsonl",
            delay_seconds=0,
            fetcher=_fake_fetcher(content_type="text/html"),
        )
        assert record.source_status == "failed"
        assert "content-type" in (record.error or "")

    def test_duplicate_hash_detected(self, tmp_path: Path) -> None:
        other = replace(ARTIFACT, file_id="ffffffffffffffffffffffffffffffff", subject_bn="রসায়ন")
        r1 = acquire_artifact(
            ARTIFACT,
            tmp_path / "raw",
            tmp_path / "m.jsonl",
            delay_seconds=0,
            fetcher=_fake_fetcher(),
        )
        r2 = acquire_artifact(
            other,
            tmp_path / "raw",
            tmp_path / "m.jsonl",
            delay_seconds=0,
            fetcher=_fake_fetcher(),
        )
        assert r1.source_status == "acquired"
        assert r2.source_status == "skipped-duplicate"

    def test_manifest_roundtrip(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "m.jsonl"
        acquire_artifact(
            ARTIFACT,
            tmp_path / "raw",
            manifest_path,
            delay_seconds=0,
            fetcher=_fake_fetcher(),
        )
        records = load_manifest(manifest_path)
        record = records[ARTIFACT.source_id]
        assert record.content_hash
        assert "T" in record.retrieved_at


class TestExtractionQc:
    def test_qc_counts(self) -> None:
        pages = [
            PageText(1, "কোষ জীবের গঠন ও কার্য নিয়ে আলোচনা করে।"),
            PageText(2, "   "),
            PageText(3, "xxxx \ufffd\ufffd\ufffd"),
        ]
        report = qc_pages(pages)
        assert report["total_pages"] == 3
        assert report["empty_pages"] == 1
        assert report["garbage_pages"] == 1
        assert report["usable_pages"] == 1
        assert report["bangla_char_ratio_on_usable"] == 1.0


class TestChunking:
    def _pages(self) -> list[PageText]:
        chapter1 = [
            "অধ্যায়: কোষ",
            f"{BANGLA_CELL} " * 8,
            "অনুশীলনী",
            ("১। কোষ কী? বিস্তারিত বর্ণনা কর এবং চিত্রসহ ব্যাখ্যা কর। " * 6),
        ]
        chapter2 = [
            "অধ্যায়: কোষ বিভাজন",
            "মাইটোসিস কোষ বিভাজনের ফলে সন্ততি কোষের সংখ্যা দ্বিগুণ হয়। " * 8,
        ]
        return [PageText(1, "\n".join(chapter1)), PageText(2, "\n".join(chapter2))]

    def test_chunks_have_chapter_provenance(self) -> None:
        chunks = chunk_pages(self._pages(), source_id="s1")
        assert chunks, "expected chunks"
        chapters = {c.chapter for c in chunks}
        assert "কোষ" in chapters
        assert "কোষ বিভাজন" in chapters

    def test_parent_ids_link_to_chapter_units(self) -> None:
        chunks = chunk_pages(self._pages(), source_id="s1")
        parents = {c.parent_id for c in chunks if c.parent_id}
        assert parents, "chapter parents must exist"

    def test_page_numbers_recorded(self) -> None:
        for chunk in chunk_pages(self._pages(), source_id="s1"):
            assert chunk.page_start >= 1 and chunk.page_end >= chunk.page_start

    def test_unusable_pages_skipped(self) -> None:
        pages = [PageText(1, ""), PageText(2, "\ufffd garbage")]
        assert chunk_pages(pages, source_id="s2") == []


class TestCorpusLoader:
    def _write_pipeline_outputs(self, tmp_path: Path) -> tuple[Path, Path]:
        extracted = tmp_path / "extracted"
        normalized = tmp_path / "normalized"
        extracted.mkdir(parents=True)
        normalized.mkdir(parents=True)

        page_texts = [
            "ষষ্ঠ শ্রেণি বিজ্ঞান",
            "অধ্যায়: কোষ",
            f"{BANGLA_CELL} " * 30,
        ]
        pages_payload = {
            "source_id": "src1",
            "pages": [{"page_number": i + 1, "text": t} for i, t in enumerate(page_texts)],
        }
        (extracted / "src1.pages.json").write_text(
            json.dumps(pages_payload, ensure_ascii=False), encoding="utf-8"
        )
        chunks = chunk_pages([PageText(**p) for p in pages_payload["pages"]], source_id="src1")
        with (normalized / "src1.chunks.jsonl").open("w", encoding="utf-8") as fh:
            for chunk in chunks:
                fh.write(json.dumps(asdict(chunk), ensure_ascii=False) + "\n")

        report = tmp_path / "quality_report.json"
        report.write_text(
            json.dumps(
                {
                    "src1": {
                        "level": "secondary",
                        "subject_bn": "বিজ্ঞান শাখার বিষয়সমূহ",
                        "curriculum_year": "2012",
                        "bangla_char_ratio_on_usable": 1.0,
                    }
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return normalized, report

    def test_loader_maps_detection_to_single_class(self, tmp_path: Path) -> None:
        assert LEVEL_CLASS_RANGE["secondary"] == (6, 10)
        assert LEVEL_CLASS_RANGE["hsc"] == (11, 12)
        normalized, report = self._write_pipeline_outputs(tmp_path)

        # stamp detection the way attach_detected_classes does
        from bangla_gpt_api.data.nctb_loader import attach_detected_classes

        detections = attach_detected_classes(normalized.parent / "extracted", normalized)
        assert detections["src1"] == 6

        chunks = load_nctb_corpus(normalized, report)
        assert chunks
        assert all(isinstance(c, Chunk) for c in chunks)
        assert {c.meta.class_level for c in chunks} == {6}
        assert all(c.meta.content_type == "nctb" for c in chunks)
        assert all(c.meta.curriculum_year == 2012 for c in chunks)

    def test_unknown_level_sources_never_loaded(self, tmp_path: Path) -> None:
        normalized, report = self._write_pipeline_outputs(tmp_path)
        payload = json.loads(report.read_text(encoding="utf-8"))
        payload["src1"]["level"] = "unknown"
        report.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        assert load_nctb_corpus(normalized, report) == []

    def test_undetected_class_falls_back_to_level_range(self, tmp_path: Path) -> None:
        normalized, report = self._write_pipeline_outputs(tmp_path)
        # remove front-matter page so nothing is detected
        pages_payload = {"source_id": "src1", "pages": []}
        (normalized.parent / "extracted" / "src1.pages.json").write_text(
            json.dumps(pages_payload, ensure_ascii=False), encoding="utf-8"
        )
        chunks = load_nctb_corpus(normalized, report)
        classes = {c.meta.class_level for c in chunks}
        assert classes == set(range(6, 11))


class TestBijoyConversion:
    REAL_BIJOY_HEADER = "RvZxq wkÿvµg 2012"
    REAL_BIJOY_SENTENCE = "evsjv‡`k‡K GKwU ga¨g Av‡qi †`‡k cwiYZ Kivi cÖavb Dcvq"

    def test_signature_detection(self) -> None:
        from bangla_gpt_api.nctb.bijoy import is_likely_legacy_bijoy

        assert is_likely_legacy_bijoy(self.REAL_BIJOY_HEADER)
        assert not is_likely_legacy_bijoy("জাতীয় শিক্ষাক্রম ২০১২")
        assert not is_likely_legacy_bijoy("")

    def test_conversion_to_unicode(self) -> None:
        from bangla_gpt_api.nctb.bijoy import conversion_quality, convert_bijoy_text

        converted = convert_bijoy_text(self.REAL_BIJOY_SENTENCE)
        assert "বাংলাদেশকে" in converted
        assert "প্রধান উপায়" in converted
        header = convert_bijoy_text(self.REAL_BIJOY_HEADER)
        assert "জাতীয়" in header and "২০১২" in header
        # the ÿ→ক্ষ post-fix must have been applied
        assert "ÿ" not in convert_bijoy_text("wkÿvµg")
        quality = conversion_quality(self.REAL_BIJOY_HEADER, header)
        assert quality["improved"] is True

    def test_extract_flags_and_converts_bijoy_pages(self) -> None:
        from unittest.mock import patch

        from bangla_gpt_api.nctb.extract import extract_pdf

        class FakePage:
            def __init__(self, text):
                self._text = text

            def extract_text(self):
                return self._text

        class FakeReader:
            pages = [
                FakePage(self.REAL_BIJOY_HEADER),
                FakePage("জাতীয় শিক্ষাক্রম সরাসরি ইউনিকোড"),
                FakePage(""),
            ]

        pdf = Path("dummy.pdf")  # never opened by FakeReader
        with patch("pypdf.PdfReader", return_value=FakeReader()):
            result = extract_pdf(pdf)
        assert result.ok
        assert result.pages[0].encoding == "bijoy-converted"
        assert "জাতীয়" in result.pages[0].text
        assert result.pages[1].encoding == "unicode"
        report = qc_pages(result.pages)
        assert report["page_encodings"] == {
            "bijoy-converted": 1,
            "unicode": 1,
            "unusable": 1,
        }


class TestSourcesInventory:
    def test_inventory_shape(self) -> None:
        from bangla_gpt_api.nctb import ALL_ARTIFACTS, HSC_ARTIFACTS, SECONDARY_ARTIFACTS

        assert len(SECONDARY_ARTIFACTS) == 16
        assert len(HSC_ARTIFACTS) == 32
        assert len(ALL_ARTIFACTS) == 48
        ids = {a.source_id for a in ALL_ARTIFACTS}
        assert len(ids) == 48
        assert all(a.url.startswith("https://objectstorage.") for a in ALL_ARTIFACTS)

    def test_find_artifact(self) -> None:
        found = find_artifact("3ce5065b")
        assert found is not None and found.subject_bn == "বাংলা"
        assert find_artifact("nonexistent-zz") is None
