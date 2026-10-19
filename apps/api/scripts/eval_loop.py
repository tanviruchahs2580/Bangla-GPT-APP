r"""A8-09 / AUD-A2-13: the online evaluation loop -- feedback to eval item.

Closes the loop the audit found open: feedback existed, traces existed, and
nothing joined them into new evaluation items.

    cd apps/api
    # 1. the API writes trace records to stdout when TRACING_ENABLED=true;
    #    capture that stream (the deployment already ships stdout to the log
    #    sink):  ... 2>&1 | tee /var/log/bangla/trace.log
    # 2. weekly triage run:
    python scripts/eval_loop.py --db ./dev.db --trace-log /var/log/bangla/trace.log \
        --since-days 7 --out eval/candidates
    # 3. a teacher/engineer fills verdicts in the triage file, then:
    python scripts/eval_loop.py --triage eval/candidates/triage_<date>.json

What it produces:

* **candidate eval items** (``candidates/candidates_<date>.jsonl``) -- one per
  rated tutor message (thumbs-down or comment-only) that has *not* been
  triaged, carrying the question (the preceding user turn), class, the rated
  answer's citations, and the joined trace record (retrieval coverage, gate
  verdict, top score, index/prompt versions, trace id). ``synthetic`` is false
  and ``needs_teacher_review`` true: a student's complaint is provenance, not
  a label.
* **a triage file** (``candidates/triage_<date>.json``) listing each candidate
  with an empty ``verdict``/``answerability`` for a human to fill.
* **approved items** (``candidates/approved_<date>.jsonl``) after
  ``--triage``: golden-shaped items (split assigned by the same sha256 rule
  the golden generator uses) that the owner merges into the set through the
  normal dataset-change path (new baseline in the same commit).
* **a privacy-safe curriculum-gap backlog** (``candidates/gap_backlog_<date>.json``):
  low-coverage traces aggregated by class and chapter with counts and mean
  coverage. No question text -- only a hashed fingerprint -- so the backlog
  can be read by ops without exposing what children asked.

The trace join is explicit: a candidate's retrieved chunk ids (recorded in the
rated message's ``sources_json``) must equal a retrieval trace's
``retrieved_ids``; the join method is recorded per candidate
(``trace_join: ids|unmatched``) and never invented -- a candidate without a
trace says so.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from bangla_gpt_api.evaluation.online_loop import (
    build_candidates,
    gap_backlog,
    load_trace_log,
    triage_candidates,
    triage_file,
)

APP_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = APP_ROOT / "eval" / "candidates"


def _ratings(db: Any, since: datetime) -> list[dict[str, Any]]:
    """Rated tutor messages with their question, class and citations."""
    from bangla_gpt_api.db.models import ChatMessage, Feedback, Student, User

    rows = (
        db.query(Feedback, ChatMessage, User)
        .join(ChatMessage, ChatMessage.id == Feedback.message_id, isouter=True)
        .join(User, User.id == Feedback.user_id)
        .filter(Feedback.created_at >= since, Feedback.message_id.is_not(None))
        .order_by(Feedback.id)
        .all()
    )
    out: list[dict[str, Any]] = []
    for feedback, message, user in rows:
        if message is None or feedback.rating not in (-1, 0):
            continue  # thumbs-up and non-message feedback are not failures
        question = (
            db.query(ChatMessage.content)
            .filter(
                ChatMessage.conversation_id == message.conversation_id,
                ChatMessage.role == "user",
                ChatMessage.id < message.id,
            )
            .order_by(ChatMessage.id.desc())
            .limit(1)
            .scalar()
        )
        student = db.query(Student).filter(Student.user_id == message_owner(db, message)).first()
        out.append(
            {
                "feedback_id": feedback.id,
                "message_id": message.id,
                "created_at": feedback.created_at.isoformat(),
                "rating": feedback.rating,
                "comment_present": bool(feedback.comment),
                "question": question or "",
                "class_level": student.class_level if student else None,
                "sources": list(message.sources_json or []),
                "grounded": message.grounded,
                "refused_reason": message.refused_reason,
                "role": user.role,
            }
        )
    return out


def message_owner(db: Any, message: Any) -> int:
    """The user id who owns the conversation a message belongs to."""
    from bangla_gpt_api.db.models import Conversation, Student

    student_id = (
        db.query(Conversation.student_id)
        .filter(Conversation.id == message.conversation_id)
        .scalar()
    )
    if student_id is None:
        return -1
    owner = db.query(Student.user_id).filter(Student.id == student_id).scalar()
    return int(owner) if owner is not None else -1


def _chapter_lookup(corpus_dir: Path | None) -> dict[str, tuple[str, str, Any]]:
    """chunk id -> (chapter, section, page), from a built corpus.

    The trace records retrieved chunk ids; the database records citations by
    (chapter, section, page). Mapping both directions through the corpus is
    what makes the join exact. Without a corpus only the weaker count join is
    available, and candidates say so.
    """
    from bangla_gpt_api.data.loader import load_sample_corpus

    if corpus_dir is not None:
        from bangla_gpt_api.data.nctb_loader import load_nctb_corpus

        chunks = load_nctb_corpus(
            corpus_dir / "normalized",
            quality_report_path=corpus_dir / "quality_report.json",
            multi_class_fallback=True,
        )
    else:
        chunks = load_sample_corpus()
    return {
        chunk.id: (chunk.meta.chapter or "", chunk.meta.section or "", chunk.meta.page)
        for chunk in chunks
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="A8-09 online evaluation loop")
    parser.add_argument("--db", type=Path, default=None, help="database URL or file path")
    parser.add_argument("--trace-log", type=Path, default=None)
    parser.add_argument(
        "--corpus-dir", type=Path, default=None, help="chapter lookup for the gap backlog"
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--since-days", type=int, default=7)
    parser.add_argument("--triage", type=Path, default=None, help="a filled triage file to apply")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if args.triage is not None:
        return _apply_triage(args)

    if args.db is None:
        parser.error("--db is required unless --triage is used")
    from bangla_gpt_api.config import Settings
    from bangla_gpt_api.db.session import make_engine, make_session_factory

    url = str(args.db)
    if not url.startswith("sqlite") and not url.startswith("postgresql"):
        url = f"sqlite:///{Path(args.db).as_posix()}"
    settings = Settings(env="test", database_url=url, llm_provider="mock")
    engine = make_engine(settings)
    session_factory = make_session_factory(engine)
    since = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=args.since_days)
    with session_factory() as db:
        ratings = _ratings(db, since)

    traces = load_trace_log(args.trace_log)
    chunk_meta = _chapter_lookup(args.corpus_dir)
    candidates, notes = build_candidates(ratings, traces, chunk_meta)
    backlog = gap_backlog(traces, chunk_meta)

    stamp = datetime.now(UTC).strftime("%Y%m%d")
    args.out.mkdir(parents=True, exist_ok=True)
    candidates_path = args.out / f"candidates_{stamp}.jsonl"
    candidates_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in candidates),
        encoding="utf-8",
    )
    triage_path = args.out / f"triage_{stamp}.json"
    triage_path.write_text(
        json.dumps(triage_file(candidates), ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    backlog_path = args.out / f"gap_backlog_{stamp}.json"
    backlog_path.write_text(
        json.dumps(backlog, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(f"feedback rows: {len(ratings)}  candidates: {len(candidates)}")
    for note in notes:
        print(f"  note: {note}")
    print(
        f"  trace join: citations={sum(1 for c in candidates if c['trace_join'] == 'citations')} "
        f"count={sum(1 for c in candidates if c['trace_join'] == 'count')} "
        f"unmatched={sum(1 for c in candidates if c['trace_join'] == 'unmatched')}"
    )
    print(f"  gap backlog: {backlog['low_coverage_traces']} low-coverage trace(s)")
    print(f"written -> {candidates_path}\n        -> {triage_path}\n        -> {backlog_path}")
    return 0


def _apply_triage(args: argparse.Namespace) -> int:
    payload = json.loads(Path(args.triage).read_text(encoding="utf-8"))
    candidates_path = Path(args.triage).with_name(
        Path(args.triage).name.replace("triage_", "candidates_").replace(".json", ".jsonl")
    )
    candidates = [
        json.loads(line)
        for line in candidates_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    approved, rejected, problems = triage_candidates(candidates, payload)
    if problems:
        for problem in problems:
            print(f"TRIAGE: FAIL -- {problem}")
        return 1
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    approved_path = Path(args.triage).with_name(f"approved_{stamp}.jsonl")
    approved_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in approved), encoding="utf-8"
    )
    print(
        f"triage applied: approved {len(approved)}  rejected {len(rejected)}  "
        f"pending {len(candidates) - len(approved) - len(rejected)}"
    )
    print(f"approved items -> {approved_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
