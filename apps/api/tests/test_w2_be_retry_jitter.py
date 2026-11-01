"""F-075: provider retry delays are jittered, and stay inside the old envelope.

The pre-fix schedule was `min(0.5 * 2**attempt, 4)` at eight call sites, so
workers that failed on the same upstream blip retried on the same second. The
budget math (`fit_timeout`, `worst_case_seconds`) must not change: the jittered
delay never exceeds the un-jittered one.
"""

import ast
from pathlib import Path

from bangla_gpt_api.providers.base import MAX_BACKOFF_SECONDS, backoff_delay_seconds

PROVIDERS = Path(__file__).resolve().parents[1] / "src" / "bangla_gpt_api" / "providers"


def _base_delay(attempt: int) -> float:
    return min(0.5 * (2**attempt), MAX_BACKOFF_SECONDS)


def test_jittered_delay_stays_inside_half_to_full_of_the_schedule() -> None:
    for attempt in range(6):
        base = _base_delay(attempt)
        for _ in range(50):
            delay = backoff_delay_seconds(attempt)
            assert 0.5 * base <= delay <= base, (attempt, delay, base)


def test_delays_are_decorrelated_across_workers() -> None:
    samples = {round(backoff_delay_seconds(3), 6) for _ in range(50)}
    assert len(samples) > 1, "every worker would retry on the same second"


def test_no_call_site_keeps_the_unjittered_schedule() -> None:
    """A new provider retry loop must use the shared helper, not the formula.

    ``base.py`` is where the formula is allowed to exist: the helper owns it.
    """
    offenders: list[str] = []
    for path in sorted(PROVIDERS.glob("*.py")):
        if path.name == "base.py":
            continue
        source = path.read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
                segment = ast.get_source_segment(source, node) or ""
                if "0.5" in segment and "2 **" in segment.replace("2**", "2 **"):
                    offenders.append(f"{path.name}:{node.lineno}: {segment}")
    assert not offenders, offenders
