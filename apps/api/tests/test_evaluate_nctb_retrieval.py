"""scripts/evaluate_nctb_retrieval.py runs end to end on a synthetic corpus.

The script's family C decides refusal by asking the *tutor* the same
grounding-gate question the API asks (``TutorService._gate``). A call to a
method the service does not expose used to crash the whole evaluation with
AttributeError before any report was written.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import asdict
from pathlib import Path
from types import ModuleType

import pytest

from bangla_gpt_api.nctb.chunking import chunk_pages
from bangla_gpt_api.nctb.extract import PageText

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "evaluate_nctb_retrieval.py"


def _write_synthetic_corpus(target: Path) -> None:
    """Same on-disk layout the corpus pipeline produces."""
    pages = [
        PageText(1, "অধ্যায়: বল ও গতি", "bijoy-converted"),
        PageText(2, "নিউটনের প্রথম সূত্র অনুযায়ী গতির অবস্থা পরিবর্তনে বাহ্যিক বল প্রয়োজন। " * 12),
    ]
    chunks = chunk_pages(pages, source_id="synthetic-nctb")
    normalized = target / "normalized"
    normalized.mkdir(parents=True)
    with (normalized / "synthetic-nctb.chunks.jsonl").open("w", encoding="utf-8") as fh:
        for chunk in chunks:
            fh.write(json.dumps(asdict(chunk), ensure_ascii=False) + "\n")
    (target / "quality_report.json").write_text(
        json.dumps(
            {
                "synthetic-nctb": {
                    "level": "secondary",
                    "subject_bn": "পদার্থবিদ্যা",
                    "curriculum_year": "2012",
                    "bangla_char_ratio_on_usable": 0.9,
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("evaluate_nctb_retrieval", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_eval_script_uses_the_tutors_real_grounding_gate(tmp_path, monkeypatch) -> None:
    corpus = tmp_path / "nctb"
    _write_synthetic_corpus(corpus)
    module = _load_script()
    monkeypatch.setattr(sys, "argv", ["evaluate_nctb_retrieval.py", str(corpus)])

    assert module.main() == 0

    report = json.loads((corpus / "retrieval_eval.json").read_text(encoding="utf-8"))
    assert report["corpus_chunks"] > 0
    # adversarial (out-of-corpus) questions must all fail the tutor's gate
    assert report["family_C_adversarial_refusal_rate"] == 1.0


def test_eval_script_refuses_to_run_without_chunks(tmp_path, monkeypatch, capsys) -> None:
    corpus = tmp_path / "empty"
    (corpus / "normalized").mkdir(parents=True)
    module = _load_script()
    monkeypatch.setattr(sys, "argv", ["evaluate_nctb_retrieval.py", str(corpus)])

    assert module.main() == 1
    assert "NO_INDEXABLE_CHUNKS" in capsys.readouterr().out


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__])
