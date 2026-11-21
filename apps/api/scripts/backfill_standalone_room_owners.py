"""Give legacy default-school classrooms back to the teacher who ran them (SEC-01).

SEC-01 walled every standalone teacher to the classrooms they are an assigned
ClassTeacher of. Rooms created before the B-07 invariant (v0.10.0,
2026-10-27) were never given that row, and ClassRoom records no creator, so
after the fix nobody but a platform admin can reach them.

The dry run lists every such orphaned room with the standalone teachers who
left work against it, and what kind of work:

* ``short_test``: short tests opened for the room;
* ``support_plan``: support plans for students enrolled in the room;
* ``assignment``: assignments whose recipients are enrolled in the room.

That evidence shows who TOUCHED a room, not who owns it. Before SEC-01 every
standalone teacher could act on every default-school room and child, so any
of it may have been created by a stranger, and the real owner may have left
none. Nothing is therefore assigned automatically: an operator confirms each
owner with the teacher out of band and passes explicit ``--assign
ROOM_ID=USER_ID`` pairs. The report carries ids, kinds and counts only,
never names, emails or other personal data.

Usage (dry run by default; prints a JSON report)::

    .venv/Scripts/python.exe apps/api/scripts/backfill_standalone_room_owners.py
    .venv/Scripts/python.exe apps/api/scripts/backfill_standalone_room_owners.py --assign 12=34

Honours ``DATABASE_URL`` exactly like the API. Assigning against a production
database is an operator action that needs the owner's approval.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from bangla_gpt_api.db.models import (  # noqa: E402
    Assignment,
    ClassRoom,
    ClassStudent,
    ClassTeacher,
    School,
    ShortTest,
    SupportPlan,
    Teacher,
    User,
)

DEFAULT_SCHOOL_CODE = "BGPT-DEFAULT"


@dataclass
class RoomPlan:
    classroom_id: int
    students: int
    #: candidate user id -> sorted evidence kinds (short_test/support_plan/assignment)
    evidence: dict[int, list[str]] = field(default_factory=dict)
    status: str = "no_evidence"  # single_candidate | ambiguous | no_evidence


def _standalone_teacher_ids(db: Session, default_id: int) -> set[int]:
    return {
        int(uid)
        for uid in db.scalars(
            select(User.id).where(
                User.role == "teacher",
                (User.school_id.is_(None)) | (User.school_id == default_id),
            )
        )
    }


def plan_backfill(db: Session) -> list[RoomPlan]:
    """One plan per default-school room that has no ClassTeacher row."""
    default_id = db.scalar(select(School.id).where(School.code == DEFAULT_SCHOOL_CODE))
    if default_id is None:
        return []
    taught = select(ClassTeacher.classroom_id)
    orphans = list(
        db.scalars(
            select(ClassRoom.id)
            .where(ClassRoom.school_id == default_id, ClassRoom.id.not_in(taught))
            .order_by(ClassRoom.id)
        )
    )
    standalone = _standalone_teacher_ids(db, default_id)
    assignments = [(a.teacher_id, a.attempts or []) for a in db.scalars(select(Assignment))]
    plans: list[RoomPlan] = []
    for room_id in orphans:
        enrolled = {
            int(s)
            for s in db.scalars(
                select(ClassStudent.student_id).where(ClassStudent.classroom_id == room_id)
            )
        }
        kinds: dict[int, set[str]] = {}
        for t in db.scalars(select(ShortTest.teacher_id).where(ShortTest.classroom_id == room_id)):
            kinds.setdefault(int(t), set()).add("short_test")
        if enrolled:
            for t in db.scalars(
                select(SupportPlan.teacher_id).where(SupportPlan.student_id.in_(sorted(enrolled)))
            ):
                kinds.setdefault(int(t), set()).add("support_plan")
            for teacher_id, attempts in assignments:
                if any(int(ref.get("student_id", -1)) in enrolled for ref in attempts):
                    kinds.setdefault(int(teacher_id), set()).add("assignment")
        evidence = {uid: sorted(k) for uid, k in sorted(kinds.items()) if uid in standalone}
        plan = RoomPlan(classroom_id=room_id, students=len(enrolled), evidence=evidence)
        if len(evidence) == 1:
            plan.status = "single_candidate"
        elif evidence:
            plan.status = "ambiguous"
        plans.append(plan)
    return plans


def apply_confirmed(db: Session, plans: list[RoomPlan], confirmed: dict[int, int]) -> list[str]:
    """Assign ONLY operator-confirmed (room -> user) pairs; returns one line per pair.

    A pair is refused unless the room is an orphan from ``plans`` and the user
    is a standalone teacher with a profile. The user need not appear in the
    evidence: the real owner may have left none.
    """
    by_room = {p.classroom_id: p for p in plans}
    default_id = db.scalar(select(School.id).where(School.code == DEFAULT_SCHOOL_CODE))
    standalone = _standalone_teacher_ids(db, default_id) if default_id is not None else set()
    results: list[str] = []
    for room_id, user_id in sorted(confirmed.items()):
        if room_id not in by_room:
            results.append(f"room {room_id}: refused (not an orphaned default-school room)")
            continue
        if user_id not in standalone:
            results.append(f"room {room_id}: refused (user {user_id} is not a standalone teacher)")
            continue
        profile = db.scalar(select(Teacher).where(Teacher.user_id == user_id))
        if profile is None:
            results.append(f"room {room_id}: refused (user {user_id} has no teacher profile)")
            continue
        db.add(ClassTeacher(classroom_id=room_id, teacher_id=profile.id, subject=""))
        results.append(f"room {room_id}: assigned to user {user_id}")
    db.commit()
    return results


def _pair(value: str) -> tuple[int, int]:
    room, _, user = value.partition("=")
    if not room.isdigit() or not user.isdigit():
        raise argparse.ArgumentTypeError("expected ROOM_ID=USER_ID")
    return int(room), int(user)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument(
        "--assign",
        type=_pair,
        action="append",
        default=[],
        metavar="ROOM_ID=USER_ID",
        help="assign one confirmed owner (repeatable); without it the run is a dry run",
    )
    args = parser.parse_args(argv)

    from bangla_gpt_api.config import Settings
    from bangla_gpt_api.db.session import make_engine, make_session_factory

    db = make_session_factory(make_engine(Settings()))()
    try:
        plans = plan_backfill(db)
        applied = apply_confirmed(db, plans, dict(args.assign)) if args.assign else []
        summary = {
            "orphaned_rooms": len(plans),
            "single_candidate": sum(p.status == "single_candidate" for p in plans),
            "ambiguous": sum(p.status == "ambiguous" for p in plans),
            "no_evidence": sum(p.status == "no_evidence" for p in plans),
            "applied": applied,
            "rooms": [asdict(p) for p in plans],
        }
        print(json.dumps(summary, indent=2))
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
