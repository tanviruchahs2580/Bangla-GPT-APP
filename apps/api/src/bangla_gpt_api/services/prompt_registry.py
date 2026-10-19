"""The prompt registry loader (A5-02/A1-04).

Prompts are versioned files under ``apps/api/prompts/`` with an owner and a
changelog in ``prompts/manifest.json``, never inline constants. This module is
the SINGLE read path, kept free of service imports so every consumer (the
tutor, the generators, the answer-structure helpers) can load from it without
an import cycle. ``services.tutor`` re-exports ``load_prompt`` for
backward-compatible imports.

A missing or malformed registry fails loudly at import time (a silent
fallback would ship a prompt nobody reviewed). ``{{age_rule}}`` is substituted
from services/safety.AGE_RULE_SENTENCE so the child-safety sentence keeps
exactly one source.

Changing a prompt means editing the file, bumping its version and adding a
changelog entry in the same change -- see docs/operations/CHANGE_MANAGEMENT.md
and prompts/README.md.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from bangla_gpt_api.services.safety import AGE_RULE_SENTENCE

PROMPTS_DIR_ENV = "BANGLA_GPT_PROMPTS_DIR"


def prompts_dir() -> Path:
    """Resolve the registry directory (env override, then the checkout)."""
    override = os.environ.get(PROMPTS_DIR_ENV, "").strip()
    if override:
        return Path(override)
    # prompt_registry.py -> services -> bangla_gpt_api -> src -> apps/api <- prompts/
    return Path(__file__).resolve().parents[3] / "prompts"


@dataclass(frozen=True)
class PromptSpec:
    """One registered prompt: text plus the metadata a trace must carry."""

    id: str
    version: str
    owner: str
    text: str

    @property
    def digest(self) -> str:
        """Content digest -- derivable, so a prompt edit cannot leave a stale
        version behind in a trace record."""
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()[:12]

    @property
    def trace_version(self) -> str:
        """Trace-visible identity: registry version + content digest."""
        return f"{self.id}@{self.version}+sp-{self.digest}"


@lru_cache(maxsize=64)
def _load_prompt_cached(prompt_id: str, directory: str | None) -> PromptSpec:
    base = Path(directory) if directory else prompts_dir()
    manifest_path = base / "manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError(
            f"prompt registry missing: {manifest_path} (set {PROMPTS_DIR_ENV} to the prompts directory)"
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = next((p for p in manifest.get("prompts", []) if p.get("id") == prompt_id), None)
    if entry is None:
        raise RuntimeError(f"prompt id {prompt_id!r} is not in {manifest_path}")
    body = (base / entry["file"]).read_text(encoding="utf-8")
    # Exactly one trailing newline is the file's line ending, never prompt text.
    if body.endswith("\n"):
        body = body[:-1]
    body = body.replace("{{age_rule}}", AGE_RULE_SENTENCE)
    return PromptSpec(
        id=prompt_id,
        version=str(entry.get("version", "0")),
        owner=str(entry.get("owner", "unowned")),
        text=body,
    )


def load_prompt(prompt_id: str, *, directory: Path | None = None) -> PromptSpec:
    """Load a registered prompt by id (see prompts/manifest.json)."""
    return _load_prompt_cached(prompt_id, str(directory) if directory else None)


__all__ = [
    "PROMPTS_DIR_ENV",
    "PromptSpec",
    "load_prompt",
    "prompts_dir",
]
