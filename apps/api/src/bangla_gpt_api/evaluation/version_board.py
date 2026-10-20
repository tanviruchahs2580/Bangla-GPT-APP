"""A10-03: the version identities a change must be judged against, in one payload.

The audit's A10-03 finding was that a model / prompt / index / embedding change
had no version visibility: the admin AI-quality board reported counts and cost
but nothing said *which* prompt, *which* index and *which* embedding model
produced them, so "did the change ship?" could not be answered from the board.

This module is the data layer for that board: :func:`version_board` collects
every identity the deployment is currently running from the artifacts that
already carry them (the prompt registry manifest, the judge prompt digest, the
index fingerprint, the thresholds register, the golden dataset hashes and the
embedding-model setting), so the endpoint only has to serialize the payload.

Wiring the endpoint is a one-line add in ``routers/admin.py`` plus a schema
field (outside this module's ownership -- the exact snippet is handed over in
.audit/handoffs/r3-ws2.md); the tests here pin the payload's content, so the
wiring cannot silently drop a version.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from bangla_gpt_api.evaluation.thresholds import default_path, load_thresholds


def _digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def prompt_manifest_versions(manifest_path: Path) -> dict[str, Any]:
    """Prompt ids and versions from the registry manifest (if present)."""
    if not manifest_path.is_file():
        return {"manifest": None, "prompts": []}
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = payload.get("prompts", payload if isinstance(payload, list) else [])
    prompts = [
        {
            key: entry.get(key)
            for key in ("id", "version", "digest", "trace_version", "module_constant")
        }
        for entry in entries
    ]
    return {
        "manifest": manifest_path.name,
        "manifest_digest": _digest(manifest_path),
        "prompts": prompts,
        "prompt_count": len(prompts),
    }


def version_board(
    api_root: Path,
    *,
    index_fingerprint: str | None = None,
    embedding_model: str | None = None,
) -> dict[str, Any]:
    """Every version identity the running evaluation pipeline is tied to.

    ``index_fingerprint`` and ``embedding_model`` come from the live app when
    the caller has a built index; when they are omitted the payload says so
    (``null``) rather than guessing -- an unknown version is a fact worth
    showing on the board.
    """
    from bangla_gpt_api.evaluation.judge import judge_prompt_path, judge_prompt_version
    from bangla_gpt_api.services.tutor import PROMPT_VERSION

    thresholds_path = default_path(api_root)
    thresholds: dict[str, Any] | None = None
    thresholds_error: str | None = None
    try:
        thresholds = load_thresholds(thresholds_path)
    except Exception as exc:  # a missing/broken register is reported, not hidden
        thresholds_error = f"{type(exc).__name__}: {exc}"

    golden_path = api_root / "eval" / "golden_v2.json"
    golden: dict[str, Any] = {"file": golden_path.name}
    if golden_path.is_file():
        payload = json.loads(golden_path.read_text(encoding="utf-8"))
        golden |= {
            "dataset_hash": payload.get("dataset_hash"),
            "test_split_hash": payload.get("test_split_hash"),
            "items": len(payload.get("items", [])),
        }

    return {
        "prompt": {
            "tutor_system": PROMPT_VERSION,
            "judge_prompt_version": judge_prompt_version(judge_prompt_path(api_root)),
        },
        "prompt_registry": prompt_manifest_versions(api_root / "prompts" / "manifest.json"),
        "index": {
            "fingerprint": index_fingerprint,
            "source": "live app when served; null means the caller had no built index",
        },
        "embedding": {
            "model": embedding_model,
            "fallback": "deterministic HashingEmbedder when the model is empty",
        },
        "evaluation": {
            "thresholds_version": None if thresholds is None else thresholds["version"],
            "thresholds_recorded_at": None if thresholds is None else thresholds["recorded_at"],
            "primary_metric": None if thresholds is None else thresholds["primary_metric"],
            "primary_split": None if thresholds is None else thresholds["primary_split"],
            "thresholds_error": thresholds_error,
            "golden": golden,
        },
        "notes": (
            "Every field is read from the artifact that owns it, never retyped. "
            "null means the caller could not supply that identity in this process; "
            "the board must render an explicit 'unknown' rather than a blank."
        ),
    }


__all__ = ["prompt_manifest_versions", "version_board"]
