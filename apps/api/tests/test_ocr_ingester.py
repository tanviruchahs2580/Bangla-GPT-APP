"""B18 — OCR ingestion adapter tests (no real tesseract required)."""

import pytest

from bangla_gpt_api.ingestion.ocr_ingester import (
    OcrPermissionDenied,
    OcrUnavailable,
    assert_ingest_permission,
    ocr_image_to_text,
)


def test_permission_gate_refuses_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BGPT_OCR_CONFIRMED", raising=False)
    with pytest.raises(OcrPermissionDenied):
        assert_ingest_permission()


def test_permission_gate_allows_when_confirmed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BGPT_OCR_CONFIRMED", "yes")
    assert_ingest_permission()


def test_ocr_unavailable_without_tesseract(monkeypatch: pytest.MonkeyPatch) -> None:
    import bangla_gpt_api.ingestion.ocr_ingester as module

    monkeypatch.setattr(module.shutil, "which", lambda name: None)
    monkeypatch.setenv("BGPT_OCR_CONFIRMED", "yes")
    with pytest.raises(OcrUnavailable):
        ocr_image_to_text("page.png", runner=lambda command: None)


def test_ocr_builds_expected_tesseract_command(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    import bangla_gpt_api.ingestion.ocr_ingester as module

    image = tmp_path / "page-001.png"
    image.write_bytes(b"fake-png")
    captured: list[list[str]] = []

    def fake_runner(command: list[str]) -> None:
        captured.append(command)

    # The test seam writes "[fixture]" next to the output base; verify plumbing.
    monkeypatch.setattr(module, "tesseract_available", lambda: True)
    text = ocr_image_to_text(image, lang="ben", psm="3", runner=fake_runner)

    assert text == "[fixture]"
    assert len(captured) == 1
    command = captured[0]
    assert command[0] == "tesseract"
    assert str(image) in command
    assert "-l" in command and "ben" in command
    assert "--psm" in command and "3" in command


def test_missing_image_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    import bangla_gpt_api.ingestion.ocr_ingester as module

    monkeypatch.setattr(module, "tesseract_available", lambda: True)
    monkeypatch.setenv("BGPT_OCR_CONFIRMED", "yes")
    with pytest.raises(FileNotFoundError):
        ocr_image_to_text("does-not-exist.png", runner=lambda command: None)
