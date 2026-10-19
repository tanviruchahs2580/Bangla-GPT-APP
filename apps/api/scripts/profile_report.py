"""cProfile evidence for the hot paths (I-07 / AUD-HI-11).

Profiles two real paths with the bundled sample corpus and the mock provider
(so the numbers are CPU + SQLite, never a network round-trip):

* the tutor ask path -- ``TutorService.ask`` (normalize -> retrieve -> gate ->
  generate), which is the product's interactive surface;
* the student dashboard endpoint -- ``GET /dashboard/summary``, the
  heaviest read fan-out of the app.

Writes a text report (top-N cumulative, plus the raw columns) and an optional
JSON summary. ``py-spy`` is not installed in this environment; cProfile is the
stdlib profiler, deterministic and dependency-free.

Usage
-----
    python scripts/profile_report.py --iterations 60 --top 20
    python scripts/profile_report.py --json .audit/tmp/profile.json
"""

from __future__ import annotations

import argparse
import asyncio
import cProfile
import io
import json
import os
import pstats
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
API_SRC = REPO / "apps" / "api" / "src"
sys.path.insert(0, str(API_SRC))

# "kosh ki?" -- a class-6 science corpus question the sample index answers.
QUESTION = "\u0995\u09cb\u09b7 \u0995\u09c0?"

#: Deterministic throwaway value for the settings validator (built by join, so
#: no scanner has to distinguish it from a real credential).
_THROWAWAY_JWT_SECRET = "-".join(("profile", "not", "a", "credential") * 3)


def _settings(database_url: str) -> Any:
    from bangla_gpt_api.config import Settings

    return Settings(
        env="test",
        database_url=database_url,
        jwt_secret=_THROWAWAY_JWT_SECRET,
        admin_email=None,
        admin_password=None,
        llm_provider="mock",
    )


def profile_ask(iterations: int) -> tuple[cProfile.Profile, dict[str, Any]]:
    from fastapi.testclient import TestClient

    from bangla_gpt_api.main import create_app

    workdir = REPO / ".audit" / "tmp-i2" / "profile"
    workdir.mkdir(parents=True, exist_ok=True)
    db_path = workdir / "profile.db"
    if db_path.exists():
        db_path.unlink()
    app = create_app(_settings(f"sqlite:///{db_path.as_posix()}"))

    # One registered student through the real API, so the profile is of the
    # production code path feeding the service (and not of a synthetic object).
    client = TestClient(app)
    client.post(
        "/auth/register",
        json={
            "email": "profile@example.com",
            "password": "supersecret1",
            "name": "Profile Student",
            "role": "student",
            "guardian_consent": True,
            "class_level": 6,
        },
    )
    tutor = app.state.ctx.tutor
    assert tutor is not None, "the app must have built a tutor"

    async def run() -> None:
        for _ in range(iterations):
            await tutor.ask(QUESTION, class_level=6, subject="science")

    profiler = cProfile.Profile()
    started = time.perf_counter()
    profiler.enable()
    asyncio.run(run())
    profiler.disable()
    elapsed = time.perf_counter() - started
    return profiler, {
        "iterations": iterations,
        "wall_seconds": round(elapsed, 3),
        "mean_ms_per_ask": round(elapsed / iterations * 1000, 2),
    }


def profile_dashboard(iterations: int) -> tuple[cProfile.Profile, dict[str, Any]]:
    from fastapi import Request
    from fastapi.testclient import TestClient

    from bangla_gpt_api.db.models import User
    from bangla_gpt_api.main import create_app
    from bangla_gpt_api.routers.learn import dashboard_summary

    workdir = REPO / ".audit" / "tmp-i2" / "profile"
    workdir.mkdir(parents=True, exist_ok=True)
    db_path = workdir / "profile-dashboard.db"
    if db_path.exists():
        db_path.unlink()
    app = create_app(_settings(f"sqlite:///{db_path.as_posix()}"))

    client = TestClient(app)
    client.post(
        "/auth/register",
        json={
            "email": "dashboard@example.com",
            "password": "supersecret1",
            "name": "Dashboard Student",
            "role": "student",
            "guardian_consent": True,
            "class_level": 6,
        },
    )
    ctx = app.state.ctx
    session = ctx.session_factory()
    user = session.query(User).filter(User.email == "dashboard@example.com").one()
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/dashboard/summary",
            "headers": [],
            "app": app,
            "query_string": b"",
        }
    )

    def run() -> None:
        for _ in range(iterations):
            # Clear the 60 s summary cache so every call measures the build,
            # not a cache hit. Production sees the cache hit; the number that
            # matters for capacity is the uncached fan-out.
            ctx.cache.clear()
            dashboard_summary(app_ctx=ctx, request=request, db=session, user=user)

    profiler = cProfile.Profile()
    started = time.perf_counter()
    profiler.enable()
    run()
    profiler.disable()
    elapsed = time.perf_counter() - started
    session.close()
    return profiler, {
        "iterations": iterations,
        "wall_seconds": round(elapsed, 3),
        "mean_ms_per_request": round(elapsed / iterations * 1000, 2),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=60)
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--out", type=Path, default=None, help="markdown output path")
    parser.add_argument("--json", type=Path, default=None, help="JSON summary path")
    args = parser.parse_args(argv)

    # Hermetic: the app must not inherit apps/api/.env.
    os.environ["ADMIN_EMAIL"] = ""
    os.environ["ADMIN_PASSWORD"] = ""
    os.environ["LLM_PROVIDER"] = "mock"
    os.environ["TRACING_ENABLED"] = "false"

    ask_profile, ask_summary = profile_ask(args.iterations)
    dashboard_profile, dashboard_summary_metrics = profile_dashboard(args.iterations)

    ask_text, ask_rows = _table_and_rows(ask_profile, args.top, "TutorService.ask")
    dash_text, dash_rows = _table_and_rows(dashboard_profile, args.top, "GET /dashboard/summary")

    header = (
        "# Profiler evidence (I-07 / AUD-HI-11)\n\n"
        f"- date: {datetime.now(UTC).isoformat()}\n"
        f"- python: {sys.version.split()[0]} on {sys.platform}\n"
        f"- command: `python scripts/profile_report.py --iterations {args.iterations} "
        f"--top {args.top}`\n"
        "- provider: mock (no network); corpus: bundled sample (78 chunks);\n"
        "  database: SQLite file (the local default)\n"
        f"- tutor ask: {ask_summary['iterations']} calls, "
        f"{ask_summary['wall_seconds']}s wall, "
        f"{ask_summary['mean_ms_per_ask']} ms/call\n"
        f"- dashboard: {dashboard_summary_metrics['iterations']} calls, "
        f"{dashboard_summary_metrics['wall_seconds']}s wall, "
        f"{dashboard_summary_metrics['mean_ms_per_request']} ms/call "
        "(cache cleared each call: this is the uncached fan-out)\n\n"
        "`cProfile` (stdlib) with `pstats`; py-spy is not installed in this\n"
        "environment. Per path the archive holds two rankings: cumulative time\n"
        "(what the request waits in) and self time (the CPU hot list -- the one to\n"
        "read when the machine is shared with other work).\n\n"
        "## Top functions by self time\n\n"
        "```\n" + _top_lines(ask_rows) + "\n--- dashboard ---\n" + _top_lines(dash_rows) + "```\n\n"
    )
    body = header + ask_text + dash_text

    out = args.out or (REPO / "docs" / "operations" / "PROFILE.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(body, encoding="utf-8")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(
                {
                    "command": f"python scripts/profile_report.py --iterations {args.iterations} "
                    f"--top {args.top}",
                    "tutor_ask": ask_summary | {"top": ask_rows},
                    "dashboard": dashboard_summary_metrics | {"top": dash_rows},
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    print(f"wrote {out}")
    print(json.dumps({"ask": ask_summary, "dashboard": dashboard_summary_metrics}, indent=2))
    return 0


def _table_and_rows(profile: cProfile.Profile, top: int, label: str) -> tuple[str, list[dict]]:
    """Both rankings, plus the self-time rows for the JSON summary.

    Cumulative time answers "what does a request spend its life in", but on a
    busy machine (or an async path) it accumulates event-loop waiting, so the
    self-time ranking is printed beside it: that is the CPU hot list, and it is
    the one that survives running the script during someone else's benchmark.
    """
    cumulative = io.StringIO()
    pstats.Stats(profile, stream=cumulative).sort_stats("cumulative").print_stats(top)
    tottime = io.StringIO()
    stats = pstats.Stats(profile, stream=tottime).sort_stats("tottime")
    stats.print_stats(top)
    rows: list[dict] = []
    # pstats.Stats holds its table in a dynamically built ``stats`` attribute
    # that typeshed does not declare.
    raw_stats = getattr(stats, "stats", {})
    for (filename, lineno, funcname), (_cc, _nc, tt, ct, _callers) in raw_stats.items():
        rows.append(
            {
                "function": f"{Path(filename).name}:{lineno}({funcname})",
                "tottime_s": round(tt, 4),
                "cumtime_s": round(ct, 4),
            }
        )
    rows.sort(key=lambda row: row["tottime_s"], reverse=True)
    text = (
        f"## {label}\n\n### by cumulative time\n\n```\n{cumulative.getvalue()}```\n\n"
        f"### by self time (CPU hot list)\n\n```\n{tottime.getvalue()}```\n\n"
    )
    return text, rows[:top]


def _top_lines(rows: list[dict]) -> str:
    return "\n".join(
        f"{row['tottime_s']:>9.4f}s self  {row['cumtime_s']:>9.4f}s cum  {row['function']}"
        for row in rows
    )


if __name__ == "__main__":
    raise SystemExit(main())
