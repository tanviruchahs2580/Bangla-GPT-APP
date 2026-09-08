"""S6.5: anonymized aggregate reporting for government/authority requests.

Implements the "aggregate export" contract: rows are per (class_level,
subject) cells of cohort-level statistics only -- counts and averages,
never per-student values. Three layers keep it PII-free:

1. The query itself only selects aggregates (distinct-student counts,
   means) -- no name/email/phone/id leaves the aggregation step.
2. k-anonymity suppression: cells with fewer than ``min_cell`` distinct
   students are dropped (and counted as suppressed) so small cohorts
   cannot be re-identified.
3. ``pii_violations()`` is a belt-and-braces automated check run before
   any export is returned; any hit fails the request closed. Tests seed
   canary PII and assert it never reaches the output.

The optional ``district`` value is a label supplied by the requesting
authority (it tags the export; it is not stored per user). CSV cells are
formula-escaped so the file is safe to open in a spreadsheet.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bangla_gpt_api.db.models import Conversation, QuizAttempt, Student

DEFAULT_MIN_CELL = 5
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONEISH_RE = re.compile(r"[+\d][\d\s-]{9,}")
# Values a spreadsheet would execute; Bangla text never starts with these.
_FORMULA_PREFIX = ("=", "+", "-", "@", "\t", "\r")


@dataclass
class AggregateMeta:
    generated_at: str
    district_tag: str
    since_days: int | None
    min_cell: int
    suppressed_cells: int
    total_students_included: int
    pii_checked: bool = True

    def as_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "district_tag": self.district_tag,
            "since_days": self.since_days,
            "min_cell": self.min_cell,
            "suppressed_cells": self.suppressed_cells,
            "total_students_included": self.total_students_included,
            "pii_checked": self.pii_checked,
        }


@dataclass
class AggregateExport:
    meta: AggregateMeta
    rows: list[dict] = field(default_factory=list)


def _csv_cell(value: object) -> str:
    text = "" if value is None else str(value)
    if text.startswith(_FORMULA_PREFIX):
        return "'" + text
    return text


def aggregate(db: Session, *, district: str = "", since_days: int | None = None,
              min_cell: int = DEFAULT_MIN_CELL) -> AggregateExport:
    """Build anonymized per-(class_level, subject) cells."""
    cutoff = None
    if since_days:
        cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=since_days)

    q = select(
        QuizAttempt.class_level,
        QuizAttempt.subject,
        func.count(func.distinct(Student.id)),
        func.count(QuizAttempt.id),
        func.avg(QuizAttempt.score_pct),
    ).join(Student, QuizAttempt.student_id == Student.id)
    if cutoff is not None:
        q = q.where(QuizAttempt.created_at >= cutoff)
    q = q.group_by(QuizAttempt.class_level, QuizAttempt.subject)

    rows: list[dict] = []
    suppressed = 0
    students_included = 0
    for class_level, subject, students, attempts, avg_score in db.execute(q):
        if students < min_cell:
            suppressed += 1
            continue
        students_included += students
        rows.append(
            {
                "class_level": class_level,
                "subject": subject or "unspecified",
                "students": students,
                "quiz_attempts": attempts,
                "avg_score_pct": round(float(avg_score), 2) if avg_score is not None else "",
            }
        )
    rows.sort(key=lambda r: (r["class_level"], r["subject"]))

    chat_q = (
        select(Student.class_level, func.count(func.distinct(Student.id)))
        .join(Conversation, Conversation.student_id == Student.id)
        .group_by(Student.class_level)
    )
    chat_by_class = {int(cl): int(n) for cl, n in db.execute(chat_q) if cl is not None}
    for row in rows:
        row["active_tutor_students"] = chat_by_class.get(row["class_level"], 0)

    meta = AggregateMeta(
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        district_tag=_csv_cell(district)[:60] if district else "",
        since_days=since_days,
        min_cell=min_cell,
        suppressed_cells=suppressed,
        total_students_included=students_included,
    )
    return AggregateExport(meta=meta, rows=rows)


CSV_COLUMNS = (
    "district",
    "class_level",
    "subject",
    "students",
    "quiz_attempts",
    "avg_score_pct",
    "active_tutor_students",
)


def to_csv(export: AggregateExport) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for row in export.rows:
        writer.writerow(
            [
                _csv_cell(export.meta.district_tag),
                _csv_cell(row["class_level"]),
                _csv_cell(row["subject"]),
                _csv_cell(row["students"]),
                _csv_cell(row["quiz_attempts"]),
                _csv_cell(row["avg_score_pct"]),
                _csv_cell(row["active_tutor_students"]),
            ]
        )
    return buf.getvalue()


def to_json_dict(export: AggregateExport) -> dict:
    return {"meta": export.meta.as_dict(), "rows": export.rows}


def pii_violations(text: str) -> list[str]:
    """Return a description list of PII-shaped patterns found in text.

    Empty list = export is safe to hand over. Called by the endpoint before
    responding and by tests with canary data.
    """
    violations: list[str] = []
    emails = EMAIL_RE.findall(text)
    if emails:
        violations.append(f"{len(emails)} email-shaped token(s)")
    phones = [p for p in PHONEISH_RE.findall(text) if not _is_safe_number(p)]
    if phones:
        violations.append(f"{len(phones)} phone-shaped digit run(s)")
    return violations


_SAFE_INTS = re.compile(r"^\d{1,3}([.\-]\d{1,3})*$")


def _is_safe_number(token: str) -> bool:
    """Class levels / scores / ISO dates are digits too -- allow plainly
    small numeric groups and timestamps, flag anything phone-like."""
    compact = token.strip()
    if _SAFE_INTS.match(compact):
        return True
    cleaned = re.sub(r"[\s\-]", "", compact)
    if cleaned.startswith(("2026", "2025", "2027")) and len(cleaned) >= 14:
        return True  # ISO timestamps
    return len(cleaned) < 10


def to_pdf(export: AggregateExport) -> bytes:
    """Render the aggregate table as PDF (fpdf2 + bundled Bengali font)."""
    from pathlib import Path

    from fpdf import FPDF

    font = Path(__file__).resolve().parent.parent / "data" / "fonts" / "NotoSansBengali-Regular.ttf"
    pdf = FPDF(format="A4")
    pdf.set_margins(15, 15, 15)
    pdf.add_page()
    pdf.add_font("nbg", style="", fname=str(font))
    pdf.set_font("nbg", size=15)
    title = "Bangla GPT Tutor - aggregate report"
    if export.meta.district_tag:
        title += f" ({export.meta.district_tag})"
    pdf.cell(w=0, h=9, text=title, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("nbg", size=9)
    pdf.set_text_color(90, 90, 90)
    meta_line = (
        f"generated: {export.meta.generated_at} | window_days: {export.meta.since_days} | "
        f"min_cell: {export.meta.min_cell} | suppressed_cells: {export.meta.suppressed_cells} | "
        f"students: {export.meta.total_students_included}"
    )
    pdf.cell(w=0, h=6, text=meta_line, new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("nbg", size=10)
    pdf.cell(
        w=0, h=8,
        text="class | subject | students | quiz_attempts | avg_score_pct | active_tutor_students",
        new_x="LMARGIN", new_y="NEXT",
    )
    pdf.set_font("nbg", size=10)
    for row in export.rows:
        pdf.cell(
            w=0, h=6,
            text=(
                f"{row['class_level']} | {row['subject']} | {row['students']} | "
                f"{row['quiz_attempts']} | {row['avg_score_pct']} | {row['active_tutor_students']}"
            ),
            new_x="LMARGIN", new_y="NEXT",
        )
    if not export.rows:
        pdf.cell(
            w=0, h=6,
            text="(no cells above the anonymity threshold)",
            new_x="LMARGIN", new_y="NEXT",
        )
    return bytes(pdf.output())


__all__ = [
    "DEFAULT_MIN_CELL",
    "AggregateExport",
    "AggregateMeta",
    "aggregate",
    "pii_violations",
    "to_csv",
    "to_json_dict",
    "to_pdf",
]
