"""A8-05: the PR-cheap evaluation gate -- replay recorded live responses.

The scheduled live run (`scripts/evaluate_live.py`) records every real provider
answer. This script replays those answers through the same pipeline in CI:
no key, no network, no spend, and byte-identical run to run, so a *code*
regression is the only thing that can move a metric.

    cd apps/api
    python scripts/evaluate_replay.py \
        --recording eval/live/2026-10-19/recorded_responses.jsonl \
        --baseline  eval/live/2026-10-19/live_generation_report.json

Exit 1 when any metric drops by more than `metrics.GATE_PP` percentage points
against the recorded run, or when the recording does not cover the questions
asked (a ReplayMissError -- see providers/replay.py: a miss must never be
silently tolerated, because a gate that cannot see its input is vacuous).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

APP_ROOT = Path(__file__).resolve().parents[1]
SRC = APP_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from bangla_gpt_api.config import Settings  # noqa: E402
from bangla_gpt_api.data.loader import load_sample_corpus  # noqa: E402
from bangla_gpt_api.evaluation.metrics import GATE_PP  # noqa: E402
from bangla_gpt_api.providers.replay import ReplayLLMProvider, ReplayMissError  # noqa: E402
from bangla_gpt_api.services.tutor import TutorService  # noqa: E402

#: Metric keys compared by the gate. Only rates the generation report always
#: produces: a key that vanishes is reported as a missing metric, not ignored.
_GATE_METRICS = (
    "citation_precision",
    "citation_precision_chapter",
    "citation_recall",
    "abstention_precision",
    "abstention_recall",
    "false_refusal_rate",
    "refusal_correctness_unsafe",
    "response_language_correctness",
    "format_validity",
)


def _rates(report: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for key in _GATE_METRICS:
        value = report.get(key)
        if isinstance(value, (int, float)):
            out[key] = float(value)
    return out


def compare_rates(baseline: dict[str, float], current: dict[str, float]) -> tuple[bool, list[str]]:
    """Fail when any shared rate drops by more than ``GATE_PP`` percentage points.

    ``metrics.compare_gate`` carries the *suite* metric names (grounded_rate,
    coverage_*), which the generation report does not produce; this comparison
    is the same rule -- one tolerance constant, the gate's own ``GATE_PP`` --
    over the generation metric set.
    """
    lines: list[str] = []
    passed = True
    for key in sorted(set(baseline) & set(current)):
        drop_pp = round((baseline[key] - current[key]) * 100.0, 4)
        ok = drop_pp <= GATE_PP + 1e-9
        if not ok:
            passed = False
        lines.append(
            f"{key}: baseline={baseline[key]:.4f} current={current[key]:.4f} "
            f"drop={drop_pp:+.2f}pp " + ("PASS" if ok else f"FAIL(>{GATE_PP:.0f}pp)")
        )
    return passed, lines


def _load_items(split: str) -> list[dict[str, Any]]:
    data: dict[str, Any] = json.loads(
        (APP_ROOT / "eval" / "golden_v2.json").read_text(encoding="utf-8")
    )
    items: list[dict[str, Any]] = data["items"]
    if split == "all":
        return items
    return [it for it in items if it.get("split", "dev") == split]


async def _run(args: argparse.Namespace) -> int:
    recording = Path(args.recording)
    baseline_path = Path(args.baseline)
    if not recording.is_absolute():
        recording = APP_ROOT / recording
    if not baseline_path.is_absolute():
        baseline_path = APP_ROOT / baseline_path
    for path in (recording, baseline_path):
        if not path.is_file():
            print(f"REPLAY: missing input {path}")
            return 1

    provider = ReplayLLMProvider.from_jsonl(recording)
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    items = _load_items(args.split)
    redteam = json.loads((APP_ROOT / "eval" / "redteam_v2.json").read_text(encoding="utf-8"))[
        "items"
    ]

    from bangla_gpt_api.evaluation.generation import run_generation_report
    from bangla_gpt_api.retrieval.embedding import build_embedder
    from bangla_gpt_api.retrieval.hybrid_index import HybridIndex
    from bangla_gpt_api.services.trace_meta import index_fingerprint

    settings = Settings(env="test", llm_provider="mock")
    index = HybridIndex(load_sample_corpus(), build_embedder(settings))
    tutor = TutorService(index=index, provider=provider, fast_provider=None)

    print(
        f"REPLAY recordings={len(provider)} items={len(items)} redteam={len(redteam)} "
        f"baseline={baseline_path.name}"
    )
    try:
        report = await run_generation_report(tutor, items, unsafe_items=redteam)
    except ReplayMissError as exc:
        print(f"REPLAY: FAIL -- {exc}")
        return 1

    current, recorded = _rates(report), _rates(baseline)
    missing = sorted(set(recorded) - set(current))
    passed, lines = compare_rates(recorded, current)
    for line in lines:
        print(f"  {line}")
    if missing:
        passed = False
        print(f"  MISSING metrics in this run: {missing}")
    print(f"  provider calls replayed={provider.served} misses={len(provider.misses)}")

    out_dir = APP_ROOT / "eval" / "tmp"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "replay_report.json").write_text(
        json.dumps(
            {
                "ran_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "recording": str(recording.name),
                "baseline": str(baseline_path.name),
                "index_fingerprint": index_fingerprint(index),
                "metrics": current,
                "baseline_metrics": recorded,
                "gate_pp": GATE_PP,
                "passed": passed,
                "detail": lines,
            },
            ensure_ascii=False,
            indent=1,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        f"REPLAY: {'PASS' if passed else 'FAIL'} (gate {GATE_PP} pp) -> {out_dir / 'replay_report.json'}"
    )
    return 0 if passed else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="A8-05 replay gate")
    parser.add_argument(
        "--recording", required=True, help="recorded_responses.jsonl from a live run"
    )
    parser.add_argument(
        "--baseline", required=True, help="live_generation_report.json from the same run"
    )
    parser.add_argument("--split", choices=["all", "dev", "test"], default="test")
    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
