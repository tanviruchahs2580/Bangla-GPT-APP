r"""A2-20 / A9-02: measured per-endpoint tokens, cost per 1,000 answers, school projection.

Drives every AI-bearing route once through the real API (TestClient, hermetic
mock provider, throwaway SQLite), then reads the usage ledger the app itself
wrote. The ledger is the measurement: ``prompt_tokens`` and
``completion_tokens`` per route, produced by ``services.costs.record_ai_usage``
at the same funnel every route already goes through. Nothing here re-estimates
what the router recorded.

Honest limits, recorded in the artifact:

* the provider is ``mock``: prompt sizes are the real prompts the routes build,
  but the *answer* side is mock-shaped (the mock quotes evidence), so
  completion tokens are a planning figure until a live run replaces them;
* the ledger's prompt side for teacher routes is a summary string (see
  ``routers/teacher_content.py`` and ``routers/common.py``), so those rows
  understate the true prompt; the report records the row as written and says so
  rather than silently scaling it;
* prices are the provider's published list prices as read on the access date
  recorded in ``evaluation/cost_model.PRICE_TABLE_CITATIONS`` (page and
  last-updated date included), not an invoice.

    cd apps/api
    python scripts/cost_report.py                    # measure + project
    python scripts/cost_report.py --budget 25        # + alert state
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

APP_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = APP_ROOT / "eval" / "cost_report.json"

#: Throwaway fixture credentials for the report's own temporary database,
#: never a real credential (gitleaks scans the tree; this is marked as one).
JWT_SECRET = "-".join(("cost", "report", "fixture") * 3)
PASSWORD = "local-fixture-password-1"  # noqa: S105 - local throwaway fixture

#: Inputs modelled on the product's own golden set and question-paper shape,
#: so the measured prompts are realistic rather than "x".
STUDENT_QUESTION = "সালোকসংশ্লেষণ কী এবং কোথায় ঘটে?"
CHAT_QUESTION = "ভগ্নাংশ কী?"
CHAPTER = "কোষ"
SUBJECT = "science"
CLASS_LEVEL = 6


def _register(client: Any, email: str, role: str) -> dict[str, str]:
    payload: dict[str, Any] = {
        "email": email,
        "password": PASSWORD,
        "name": "Cost Report",
        "role": role,
    }
    if role == "student":
        payload.update({"class_level": CLASS_LEVEL, "guardian_consent": True})
    response = client.post("/auth/register", json=payload)
    if response.status_code != 201:
        raise SystemExit(f"register {email}: {response.status_code} {response.text}")
    login = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    if login.status_code != 200:
        raise SystemExit(f"login {email}: {login.status_code} {login.text}")
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def drive_endpoints(client: Any) -> dict[str, str]:
    """One real call per AI-bearing route; returns route -> outcome note."""
    notes: dict[str, str] = {}
    student = _register(client, "cost-student@example.com", "student")
    teacher = _register(client, "cost-teacher@example.com", "teacher")

    response = client.post(
        "/tutor/ask",
        json={"question": STUDENT_QUESTION, "class_level": CLASS_LEVEL, "subject": SUBJECT},
        headers=student,
    )
    notes["tutor.ask"] = f"status={response.status_code}"

    conversation = client.post(
        "/tutor/conversations", json={"title": "cost report"}, headers=student
    )
    if conversation.status_code != 201:
        notes["tutor.chat"] = f"conversation create failed: {conversation.status_code}"
    else:
        conversation_id = conversation.json()["id"]
        response = client.post(
            f"/tutor/conversations/{conversation_id}/messages",
            json={"message": CHAT_QUESTION, "class_level": CLASS_LEVEL},
            headers=student,
        )
        notes["tutor.chat"] = f"status={response.status_code}"
        with client.stream(
            "POST",
            f"/tutor/conversations/{conversation_id}/messages/stream",
            json={"message": CHAT_QUESTION, "class_level": CLASS_LEVEL},
            headers=student,
        ) as stream:
            for _line in stream.iter_lines():
                pass
        notes["tutor.chat.stream"] = f"status={stream.status_code}"

    response = client.post(
        "/teacher/generate/worksheet",
        json={
            "class_level": CLASS_LEVEL,
            "subject": SUBJECT,
            "chapter": CHAPTER,
            "gen": {"count": 5},
        },
        headers=teacher,
    )
    notes["teacher/worksheet"] = f"status={response.status_code}"

    response = client.post(
        "/teacher/generate/rubric",
        json={"class_level": CLASS_LEVEL, "subject": SUBJECT, "chapter": CHAPTER, "gen": {}},
        headers=teacher,
    )
    notes["teacher/rubric"] = f"status={response.status_code}"

    response = client.post(
        "/teacher/qpapers",
        json={
            "class_level": CLASS_LEVEL,
            "subject": SUBJECT,
            "chapters": [CHAPTER],
            "exam_type": "half-yearly",
            "marks": 10,
            "duration_min": 20,
            "difficulty": {"easy": 30, "medium": 50, "hard": 20},
        },
        headers=teacher,
    )
    notes["teacher/question_paper"] = f"status={response.status_code}"

    response = client.post(
        "/teacher/generate/lesson_plan",
        json={
            "class_level": CLASS_LEVEL,
            "subject": SUBJECT,
            "chapter": CHAPTER,
            "gen": {"minutes": 30, "level": "basic"},
        },
        headers=teacher,
    )
    notes["teacher/lesson_plan"] = f"status={response.status_code}"
    return notes


class _TraceCapture:
    """Collect ``trace`` log records so the true prompt size is visible.

    The tutor emits one generation trace per call whose ``prompt_tokens`` is
    the estimator run over the *actual* prompt (system rules, education
    context, evidence blocks); the usage ledger records the question string
    for tutor routes. Capturing both is the point: the ledger is what budgets
    and alerts run on today, and the gap is a cost-accuracy finding, not a
    detail to smooth over.
    """

    def __init__(self) -> None:
        import logging

        self.records: list[dict] = []
        self._logger = logging.getLogger("bangla_gpt_api.trace")
        self._logger.setLevel(logging.INFO)
        self._handler = logging.Handler()
        self._handler.emit = self._emit  # type: ignore[method-assign]
        self._logger.addHandler(self._handler)

    def _emit(self, record) -> None:  # noqa: ANN001
        try:
            payload = json.loads(record.getMessage())
        except (TypeError, ValueError):
            return
        if payload.get("event") == "trace" and payload.get("stage") == "generation":
            self.records.append(payload)

    def close(self) -> None:
        self._logger.removeHandler(self._handler)


def build_report(
    *,
    model: str,
    budget_usd: float,
    assumptions: dict[str, float],
    workdir: Path,
) -> tuple[dict, dict[str, str]]:
    # The env must be set BEFORE the import: importing bangla_gpt_api.main
    # builds the module-level app for gunicorn, and without these it would use
    # the developer .env database (same rule as scripts/bench_dashboards.py).
    import os

    db_path = workdir / "cost.db"
    os.environ["ENV"] = "test"
    os.environ["LLM_PROVIDER"] = "mock"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"

    from fastapi.testclient import TestClient

    from bangla_gpt_api.config import Settings
    from bangla_gpt_api.db.models import AiUsage
    from bangla_gpt_api.db.session import make_engine, make_session_factory
    from bangla_gpt_api.evaluation.cost_model import (
        budget_alert_state,
        cost_per_1000_answers,
        price_table_with_citations,
        school_monthly_projection,
        verify_price_table,
    )
    from bangla_gpt_api.main import create_app

    settings = Settings(
        env="test",
        llm_provider="mock",
        database_url=f"sqlite:///{db_path.as_posix()}",
        jwt_secret=JWT_SECRET,
        tracing_enabled=True,
    )
    app: Any = create_app(settings)
    capture = _TraceCapture()
    try:
        client = TestClient(app)
        notes = drive_endpoints(client)
    finally:
        capture.close()

    engine = make_engine(settings)
    session_factory = make_session_factory(engine)
    with session_factory() as db:
        rows = db.query(AiUsage).order_by(AiUsage.id).all()
        measured: list[dict[str, Any]] = [
            {
                "route": row.route,
                "model": row.model,
                "prompt_tokens": row.prompt_tokens,
                "completion_tokens": row.completion_tokens,
                "cost_usd_per_answer": round(row.estimated_cost_usd, 8),
            }
            for row in rows
        ]

    # Pair each ledger row, in order, with a generation trace of the same
    # completion size (both estimators run over the same answer text, so the
    # values are equal by construction). Unpaired rows say so.
    traces = list(capture.records)
    for row in measured:
        match = next(
            (
                trace
                for trace in traces
                if trace.get("completion_tokens") == row["completion_tokens"]
            ),
            None,
        )
        if match is not None:
            traces.remove(match)
            row["true_prompt_tokens"] = match.get("prompt_tokens")
            row["trace_paired"] = True
        else:
            row["true_prompt_tokens"] = None
            row["trace_paired"] = False

    per_route_tokens = {
        str(row["route"]): (
            int(row["true_prompt_tokens"] or row["prompt_tokens"]),
            int(row["completion_tokens"]),
        )
        for row in measured
    }
    for row in measured:
        row["cost_per_1000_answers_usd"] = cost_per_1000_answers(
            model, int(row["prompt_tokens"]), int(row["completion_tokens"])
        )
        row["cost_per_1000_answers_true_prompt_usd"] = cost_per_1000_answers(
            model,
            int(row["true_prompt_tokens"] or row["prompt_tokens"]),
            int(row["completion_tokens"]),
        )
    projection = school_monthly_projection(
        model=model, per_route_tokens=per_route_tokens, assumptions=assumptions
    )
    report = {
        "generated_by": "scripts/cost_report.py",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "model": model,
        "provider": "mock (hermetic; replace completion tokens with a live run's "
        "ledger before procurement)",
        "prices": price_table_with_citations(),
        "price_table_mismatches": verify_price_table(),
        "endpoint_notes": notes,
        "ledger_vs_true_prompt": _prompt_gap(measured),
        "measured_per_endpoint": measured,
        "projection": projection,
        "budget_alert": budget_alert_state(projection["monthly_usd"], budget_usd),
        "caveats": [
            "prompt tokens are the real prompts the routes built (app estimator, "
            "~4 chars/token, over-counts short ASCII and under-counts long Bangla)",
            "completion tokens are mock-shaped: the mock quotes retrieved evidence",
            "teacher routes record a summary prompt string, so their prompt side "
            "understates the true prompt",
            "list prices, not an invoice: the provider's page and the date it was "
            "read are in prices.<model>.source / .accessed",
        ],
    }
    return report, notes


def _prompt_gap(measured: list[dict]) -> dict:
    """Ledger-recorded prompt tokens versus the true prompt the tracer saw."""
    paired = [row for row in measured if row["trace_paired"]]
    ledger_total = sum(row["prompt_tokens"] for row in measured)
    true_total = sum(row["true_prompt_tokens"] or row["prompt_tokens"] for row in measured)
    return {
        "rows": len(measured),
        "rows_with_trace": len(paired),
        "ledger_prompt_tokens_total": ledger_total,
        "true_prompt_tokens_total": true_total,
        "undercount_factor": round(true_total / ledger_total, 3) if ledger_total else None,
        "note": (
            "tutor routes ledger the question string while the model receives the full "
            "prompt (system rules + context + evidence): budgets and cost per 1,000 "
            "answers computed from the ledger alone understate the input side; the "
            "projection below uses the traced prompt where available"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="A2-20/A9-02 cost report")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--model", default="gemini-3.1-flash-lite")
    parser.add_argument("--budget", type=float, default=0.0, help="AI_MONTHLY_BUDGET_USD")
    parser.add_argument("--students", type=float, default=400)
    parser.add_argument("--asks-per-student", type=float, default=40)
    parser.add_argument("--chat-turns-per-student", type=float, default=20)
    parser.add_argument("--teacher-generations", type=float, default=80)
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    assumptions = {
        "students": args.students,
        "student_asks_per_student_per_month": args.asks_per_student,
        "chat_turns_per_student_per_month": args.chat_turns_per_student,
        "teacher_generations_per_month": args.teacher_generations,
    }
    # The throwaway database cannot be unlinked on Windows while the app's
    # module-level engine still holds it open (the same constraint
    # scripts/bench_dashboards.py documents), so cleanup is best-effort.
    workdir = Path(tempfile.mkdtemp(prefix="bgpt-cost-"))
    report, _notes = build_report(
        model=args.model,
        budget_usd=args.budget,
        assumptions=assumptions,
        workdir=workdir,
    )
    shutil.rmtree(workdir, ignore_errors=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(
        f"model {report['model']}  price mismatches: {report['price_table_mismatches'] or 'none'}"
    )
    gap = report["ledger_vs_true_prompt"]
    print(
        f"prompt tokens: ledger {gap['ledger_prompt_tokens_total']} vs traced "
        f"{gap['true_prompt_tokens_total']} ({gap['undercount_factor']}x)"
    )
    print(
        f"{'route':<26} {'ledger in':>9} {'true in':>8} {'out':>6} "
        f"{'USD/1k (ledger)':>16} {'USD/1k (true)':>14}"
    )
    for row in report["measured_per_endpoint"]:
        print(
            f"{row['route']:<26} {row['prompt_tokens']:>9} "
            f"{row['true_prompt_tokens']!s:>8} {row['completion_tokens']:>6} "
            f"{row['cost_per_1000_answers_usd']:>16} "
            f"{row['cost_per_1000_answers_true_prompt_usd']:>14}"
        )
    projection = report["projection"]
    print(
        f"\nprojection: ${projection['monthly_usd']} / month for "
        f"{projection['assumptions']['students']:.0f} students "
        f"(${projection['monthly_usd_per_student']} per student)"
    )
    for route, block in projection["per_route"].items():
        print(f"  {route:<26} {block['monthly_calls']:>10.0f} calls  ${block['monthly_usd']}")
    print(f"budget alert: {report['budget_alert']['message']}")
    print(f"\nwritten -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
