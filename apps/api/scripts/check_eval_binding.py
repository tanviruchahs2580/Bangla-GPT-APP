"""Verify that a committed evaluation baseline still describes reality.

WHY THIS EXISTS

`apps/api/eval/baseline_v3.json` is the artefact the blocking regression gate
compares against. Until now it recorded rates and nothing else: not the corpus
they were measured on, not the embedder, not the prompt. A rate without an
identity is unattributable, so two failure modes were invisible:

1. **Silent drift.** Change the embedder, the prompt, or the sample corpus and
   the committed baseline keeps describing the old one. Every later comparison
   is then made against numbers produced by different code, and nothing fails.
2. **Wrong-corpus confidence.** The golden suite is hermetic -- it measures the
   bundled sample corpus, not the NCTB corpus the product serves -- but no
   committed artefact said so. A green gate reads as "retrieval is healthy"
   when it means "retrieval is healthy on 78 synthetic chunks".

This checker closes (1) and makes (2) legible. It does not close (2): binding the
benchmark to the served corpus needs a corpus-derived evaluation set, which is a
separate, reviewed act.

HOW IT BEHAVES

- Baseline declares an identity that matches the code -> exit 0.
- Baseline declares an identity that does not match     -> exit 1, field by field.
- Baseline declares no identity (predates this field)   -> exit 0 with a notice.

That last case is deliberate. Failing on it would red CI until the baseline is
regenerated, and regenerating a baseline is never done in the same change as the
code it would mask (project rule, AGENTS.md 11). The notice states the gap; the
regeneration is its own reviewed change. Once that lands this becomes strict
automatically, with no edit here.

Usage::

    python3 apps/api/scripts/check_eval_binding.py
    python3 apps/api/scripts/check_eval_binding.py --baseline path/to/baseline.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
DEFAULT_BASELINE = REPO / "apps" / "api" / "eval" / "baseline_v3.json"

#: Fields compared, and what to do about a difference. Everything here is
#: identity: if any of these move, the committed rates no longer describe the
#: code that is running.
COMPARED = (
    "corpus_source",
    "corpus_chunk_count",
    "served_chunks_digest",
    "embedder_name",
    "embedding_dimension",
    "prompt_version",
    "prompt_sha256",
)


def current_identity() -> dict:
    """The identity the code has right now, computed the same way the writer does."""
    sys.path.insert(0, str(REPO / "apps" / "api" / "src"))
    from bangla_gpt_api.config import Settings
    from bangla_gpt_api.evaluation.cli import _evidence_identity

    # Same hermetic settings the gate uses, so this cannot be a different
    # configuration reading back a different identity.
    return _evidence_identity(Settings(env="test", llm_provider="mock"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    args = parser.parse_args()

    if not args.baseline.is_file():
        print(f"::error::baseline not found: {args.baseline}")
        return 1

    recorded = json.loads(args.baseline.read_text(encoding="utf-8")).get("identity")
    actual = current_identity()

    if not recorded:
        print(
            f"::notice:: {args.baseline.name} records no identity, so it cannot prove "
            "which corpus, embedder or prompt its rates describe. It predates "
            "identity binding. Regenerate it as its own reviewed change -- never "
            "in the same change as the retrieval code it would mask."
        )
        print(f"  current identity: {json.dumps(actual, ensure_ascii=True, sort_keys=True)}")
        return 0

    drifted = [
        (field, recorded.get(field, "<absent>"), actual.get(field, "<absent>"))
        for field in COMPARED
        if recorded.get(field, "<absent>") != actual.get(field, "<absent>")
    ]

    if drifted:
        print(
            f"::error:: {args.baseline.name} no longer describes this code. "
            "A baseline must be regenerated when its corpus, embedder or prompt "
            "changes -- otherwise every later comparison is made against numbers "
            "produced by different code."
        )
        for field, was, now in drifted:
            print(f"  {field}: baseline={was!r}  actual={now!r}")
        print("\n  Regenerate with: python -m bangla_gpt_api.evaluation.cli --write-baseline")
        return 1

    print(
        f"eval binding OK: {args.baseline.name} describes "
        f"{actual['corpus_source']} ({actual['corpus_chunk_count']} chunks), "
        f"{actual['embedder_name']} dim={actual['embedding_dimension']}, "
        f"{actual['prompt_version']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
