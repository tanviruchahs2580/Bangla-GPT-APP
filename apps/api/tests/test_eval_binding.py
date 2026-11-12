"""Regression guards for evaluation-artefact identity binding.

`apps/api/eval/baseline_v3.json` is the artefact the blocking regression gate
compares against. Until this change it recorded rates and nothing else -- not
the corpus they were measured on, not the embedder, not the prompt. A rate
without an identity is unattributable, and that produced a defect worth naming:

**The gate measures the bundled sample corpus, not the corpus the product
serves.** Every retrieval path in `evaluation/cli.py` calls
``load_sample_corpus()``, so the committed rates describe 78 synthetic chunks.
A green gate reads as "retrieval is healthy" when what it establishes is
"retrieval is healthy on 78 synthetic chunks". Nothing in the artefacts said so.

These tests pin the three behaviours that close the *drift* half of that gap and
make the *binding* half legible:

1. the writer records a corpus/embedder/prompt identity;
2. the checker accepts a baseline whose identity matches the code;
3. the checker REJECTS a baseline whose identity has drifted (a swapped embedder
   is the realistic case -- `EMBEDDING_MODEL` is an operator setting and changing
   it is a manifest-breaking event).

They deliberately do not assert that the identity binds the served NCTB corpus.
It does not: that needs a corpus-derived evaluation set, which is a separate,
reviewed act.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
CHECKER = REPO / "apps" / "api" / "scripts" / "check_eval_binding.py"
COMMITTED_BASELINE = REPO / "apps" / "api" / "eval" / "baseline_v3.json"

#: Minimal well-formed-ish baseline: the checker only reads `identity`, so the
#: rest of the shape does not matter for these guards.
BASE = {"recorded_by": "test", "version": "golden-v3.0.0", "n": 1, "metrics": {}}


def _current_identity() -> dict:
    """Ask the checker for the live identity rather than hardcoding it.

    Hardcoding would make these tests pass after an embedder change, which is
    the exact failure they exist to catch.
    """
    done = subprocess.run(
        [sys.executable, str(CHECKER)],
        capture_output=True,
        text=True,
        cwd=REPO / "apps" / "api",
    )
    assert "current identity: " in done.stdout, done.stdout + done.stderr
    return json.loads(done.stdout.split("current identity: ", 1)[1].strip())


def _run_checker(baseline: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CHECKER), "--baseline", str(baseline)],
        capture_output=True,
        text=True,
        cwd=REPO / "apps" / "api",
    )


def test_identity_names_the_corpus_actually_measured():
    """The identity must say `bundled_sample`, because that is the truth.

    If this ever flips to a corpus path, the suite stopped being hermetic and
    the change that did it needs to be deliberate and reviewed.
    """
    identity = _current_identity()
    assert identity["corpus_source"] == "bundled_sample"
    assert identity["corpus_chunk_count"] == 78, "sample corpus is 78 chunks"
    assert identity["embedder_name"] == "hash-ngram-local"
    assert identity["embedding_dimension"] == 384
    assert identity["prompt_version"] == "tutor-prompt-v1"
    assert len(identity["prompt_sha256"]) == 64, "sha256 hex digest"
    assert identity["served_chunks_digest"]


def test_checker_accepts_a_matching_identity(tmp_path: Path):
    baseline = tmp_path / "matching.json"
    baseline.write_text(
        json.dumps({**BASE, "identity": _current_identity()}), encoding="utf-8"
    )
    done = _run_checker(baseline)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "eval binding OK" in done.stdout
    assert "bundled_sample (78 chunks)" in done.stdout


def test_checker_rejects_a_drifted_embedder(tmp_path: Path):
    """A swapped embedder invalidates every committed rate.

    This is the realistic drift: `EMBEDDING_MODEL` is an operator setting, and
    adopting a semantic model changes both the name and the dimension.
    """
    drifted = {**_current_identity(), "embedder_name": "bge-m3", "embedding_dimension": 1024}
    baseline = tmp_path / "drifted.json"
    baseline.write_text(json.dumps({**BASE, "identity": drifted}), encoding="utf-8")

    done = _run_checker(baseline)
    assert done.returncode == 1, "a drifted identity must fail the gate"
    assert "no longer describes this code" in done.stdout
    assert "embedder_name: baseline='bge-m3'" in done.stdout
    assert "embedding_dimension: baseline=1024" in done.stdout
    # The failure has to say what to do, not just that something is wrong.
    assert "--write-baseline" in done.stdout


def test_checker_rejects_a_drifted_prompt(tmp_path: Path):
    """A prompt change moves the numbers, so it must move the baseline too."""
    drifted = {**_current_identity(), "prompt_version": "tutor-prompt-v2"}
    baseline = tmp_path / "drifted-prompt.json"
    baseline.write_text(json.dumps({**BASE, "identity": drifted}), encoding="utf-8")

    done = _run_checker(baseline)
    assert done.returncode == 1
    assert "prompt_version: baseline='tutor-prompt-v2'" in done.stdout


def test_missing_identity_notices_but_does_not_fail(tmp_path: Path):
    """A pre-binding baseline is a documented gap, not a build breaker.

    Failing here would red CI until the baseline is regenerated, and a baseline
    is never regenerated in the same change as the code it would mask (project
    rule). So the checker states the gap and the regeneration is its own
    reviewed change -- after which this test's sibling above takes over.
    """
    baseline = tmp_path / "legacy.json"
    baseline.write_text(json.dumps(BASE), encoding="utf-8")

    done = _run_checker(baseline)
    assert done.returncode == 0
    assert "records no identity" in done.stdout
    assert "::notice::" in done.stdout


def test_the_committed_baseline_is_either_bound_or_flagged():
    """The real artefact: bound, or explicitly flagged as unbound.

    Written as a disjunction on purpose. The honest current state is 'unbound'
    and this test records it rather than asserting a property the artefact does
    not have. It flips to the strict branch by itself once the baseline is
    regenerated with an identity.
    """
    baseline = json.loads(COMMITTED_BASELINE.read_text(encoding="utf-8"))
    recorded = baseline.get("identity")

    if recorded is None:
        done = _run_checker(COMMITTED_BASELINE)
        assert done.returncode == 0
        assert "records no identity" in done.stdout
    else:
        assert recorded == _current_identity(), (
            "the committed baseline declares an identity that no longer matches "
            "the code -- regenerate it as its own reviewed change"
        )


def test_identity_shape_is_stable():
    """The compared field set is a contract with `checker.COMPARED`.

    Adding a field to the writer without adding it to the comparison would let
    it drift silently, which is the whole point of the mechanism.
    """
    from scripts.check_eval_binding import COMPARED  # type: ignore[import-not-found]

    assert set(COMPARED) <= set(_current_identity()), (
        "every compared field must exist in the recorded identity"
    )
    # corpus_path is informational: it is not compared, because a corpus can move
    # without changing what was measured (digest + count cover that).
    assert "corpus_path" not in COMPARED


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
