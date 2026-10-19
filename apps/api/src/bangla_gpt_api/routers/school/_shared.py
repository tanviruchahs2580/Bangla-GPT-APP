"""Shared tenancy helpers for the school routes.

Extracted verbatim from ``routers/school.py`` when the 1060-line module was
split into the ``school`` package (C-03): the scope resolution, the room /
roster lookups and the school-code generator are used by more than one of the
submodules, so they live in one place instead of being copied per file.
"""

import secrets

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from bangla_gpt_api.db.models import ClassRoom, ClassStudent, School, Student, User

from ..common import SCHOOL_CODE_ALPHABET, _default_school

#: "strong" bucket threshold for the school dashboard (percent).
#: The at-risk rule itself comes from (services/atrisk.py).
SCHOOL_STRONG_AVG = 70.0


def _gen_school_code(db: Session, length: int = 8) -> str:
    while True:
        code = "".join(secrets.choice(SCHOOL_CODE_ALPHABET) for _ in range(length))
        clash = db.execute(select(School.id).where(School.code == code)).first()
        if clash is None:
            return code


def _school_or_403(user: User, school_id: int) -> None:
    """school_admin may act on their own school only; admin on any."""
    if user.role == "admin":
        return
    if user.role == "school_admin" and user.school_id == school_id:
        return
    raise HTTPException(
        status_code=403,
        detail={"code": "other_school", "message": "Scoped to your own school"},
    )


def _actor_school(db: Session, user: User, school_id: int | None) -> School:
    """Resolve the school a /school/* request is allowed to read.

    school_admin is hard-scoped to their own row; platform admin may name
    any school and falls back to the default school (same rule as
    /school/overview).
    """
    if user.role == "school_admin":
        if school_id is not None and school_id != user.school_id:
            raise HTTPException(
                status_code=403,
                detail={"code": "other_school", "message": "Scoped to your own school"},
            )
        school = db.get(School, user.school_id) if user.school_id else None
        if school is None:
            raise HTTPException(status_code=404, detail="school not found")
        return school
    school = db.get(School, school_id) if school_id else None
    if school is None:
        school = _default_school(db)
    return school


def _school_rooms(db: Session, school_id: int) -> list[ClassRoom]:
    return list(
        db.execute(
            select(ClassRoom)
            .where(ClassRoom.school_id == school_id)
            .order_by(ClassRoom.class_level, ClassRoom.section, ClassRoom.id)
        ).scalars()
    )


def _school_students_by_room(
    db: Session, room_ids: list[int]
) -> tuple[list[Student], dict[int, int]]:
    """Enrolled students (school membership is classroom membership) plus
    the room each student belongs to (v1 rule: exactly one room)."""
    room_of: dict[int, int] = {}
    if not room_ids:
        return [], room_of
    for sid, rid in db.execute(
        select(ClassStudent.student_id, ClassStudent.classroom_id)
        .where(ClassStudent.classroom_id.in_(room_ids))
        .order_by(ClassStudent.classroom_id, ClassStudent.student_id)
    ).all():
        room_of.setdefault(int(sid), int(rid))
    ids = sorted(room_of)
    if not ids:
        return [], room_of
    rows = {s.id: s for s in db.execute(select(Student).where(Student.id.in_(ids))).scalars().all()}
    return [rows[i] for i in ids if i in rows], room_of
