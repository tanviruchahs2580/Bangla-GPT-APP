"""Recorded-response replay provider (A8-05).

PR CI must be able to run the evaluation gate against *real* provider responses
without a key, without network and without spending money, and it must be
deterministic. This provider serves exactly the responses a live run recorded
(`apps/api/eval/live/<date>/recorded_responses.jsonl`, written by
`scripts/evaluate_live.py`), keyed by a digest of the exact prompt sent.

Failure is loud by design: a prompt with no recording raises
:class:`ReplayMissError` instead of falling back to a model or to an empty
answer. A silent miss would turn a prompt change into a metric that looks fine
-- the class of vacuous gate the audit treats as a defect.

Recorded responses contain user-facing answers and no credentials; the live
script never records the prompt text itself, only its digest and length.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from bangla_gpt_api.providers.base import LLMProvider, ProviderError


class ReplayMissError(ProviderError):
    """The asked prompt was never recorded -- the gate must not guess."""


def digest(prompt: str, system: str | None, image: dict | None) -> str:
    """Same key the live recorder uses (see scripts/evaluate_live.py)."""
    h = hashlib.sha256()
    for part in (prompt, system or "", (image or {}).get("data", "")[:64]):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:32]


class ReplayLLMProvider:
    """Replays recorded answers; raises on an unknown prompt."""

    def __init__(self, recordings: dict[str, dict[str, Any]], *, name: str = "replay") -> None:
        self._by_digest = dict(recordings)
        self.name = name
        # Recordings may carry images (the vision lane); the live recordings in
        # this repo are text-only, so declare no vision rather than pretend.
        self.supports_vision = any(rec.get("has_image") for rec in recordings.values())
        # Recorded answers are fixed text: sampling is meaningless here, and
        # declaring support keeps the caller's kwargs flowing unchanged.
        self.supports_sampling = True
        self.served = 0
        self.misses: list[str] = []

    @classmethod
    def from_jsonl(cls, path: Path) -> ReplayLLMProvider:
        recordings: dict[str, dict[str, Any]] = {}
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                recordings[rec["digest"]] = rec
        if not recordings:
            raise ValueError(f"{path} holds no recordings")
        return cls(recordings)

    def __len__(self) -> int:
        return len(self._by_digest)

    async def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        image: dict | None = None,
        sampling: Any = None,
    ) -> str:
        key = digest(prompt, system, image)
        rec = self._by_digest.get(key)
        if rec is None:
            self.misses.append(key)
            raise ReplayMissError(
                f"no recorded response for prompt digest {key} "
                f"(prompt_chars={len(prompt)}); re-run scripts/evaluate_live.py"
            )
        self.served += 1
        return str(rec["answer"])

    async def stream(
        self,
        prompt: str,
        *,
        system: str | None = None,
        image: dict | None = None,
        sampling: Any = None,
    ) -> AsyncIterator[str]:
        answer = await self.generate(prompt, system=system, image=image, sampling=sampling)
        # Chunking is irrelevant to the metrics and a fixed split keeps the
        # replay byte-identical run to run.
        for start in range(0, len(answer), 120):
            yield answer[start : start + 120]

    async def aclose(self) -> None:  # pragma: no cover - nothing to release
        return None


__all__ = ["LLMProvider", "ReplayLLMProvider", "ReplayMissError", "digest"]
