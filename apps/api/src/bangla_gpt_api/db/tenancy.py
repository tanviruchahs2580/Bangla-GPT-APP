"""Central ORM tenancy filter (B-08).

The tenancy anchor is ``User.school_id``: a student belongs to a school
exactly when one of their ClassRoom memberships carries that ``school_id``
(see ``routers/deps.py``). Enforcement used to live only in per-router helper
calls, so a new query that forgot ``_assert_student_in_school`` was one review
slip away from a cross-school read. This module makes the read path central:
when a request is authenticated as school-scoped staff, the session carries
the tenant and every ORM ``select()`` against the tenancy ANCHOR models is
rewritten with a ``with_loader_criteria`` filter -- an ORM-level equivalent
of the helper's predicate, applied without touching any call site.

What is filtered (the anchors every other tenant-scoped row hangs off):

* ``ClassRoom``   -- ``school_id == tenant``
* ``ClassStudent``-- enrollment into a classroom of the tenant's school
* ``Student``     -- the student set derived from those enrollments (the
  exact set ``_school_student_id_set`` computes for the helpers)

Deliberately NOT filtered:

* Role-scoped sessions get no filter at all: admin sees everything;
  student/parent sessions query their own rows through ownership checks.
* Writes (INSERT/UPDATE/DELETE statements) are not rewritten: a missed
  write guard should fail loudly in its own test, not silently no-op.
* The tenancy helpers' own by-id load: ``routers.deps.load_student_for_tenant``
  reads the pre-image with the filter bypassed (``tenant_filter_bypassed``),
  then applies the same predicate explicitly. That preserves the documented
  403 ``other_school`` contract for a row that exists outside the tenant
  while a plain filtered read of the same row answers 404 (invisible) --
  see the helper's docstring. The bypass is scoped to that helper; a
  bypassed read is never followed by anything but an explicit check.

``Session.get()`` note (verified against SQLAlchemy 2.1): a get that hits the
database DOES emit ``do_orm_execute`` and is therefore filtered, but a get
served from the identity map (the row was already loaded in this session)
does not. In a request, the tenant is installed before the route runs, so
every route-level load is filtered; a session that loads tenant rows before
installing the context (only get_current_user's own lookups) is the one case,
and those are ``User``/``School`` rows -- not anchor models.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import event, select
from sqlalchemy.orm import Session, sessionmaker, with_loader_criteria

from bangla_gpt_api.db.models import ClassRoom, ClassStudent, Student

#: Key on ``Session.info`` holding the request's tenant school id.
TENANT_SCHOOL_ID_KEY = "tenant_school_id"
#: Key that temporarily suspends the filter for one deliberate pre-image read.
_TENANT_FILTER_BYPASS_KEY = "tenant_filter_bypass"


@contextmanager
def tenant_filter_bypassed(session: Session) -> Iterator[None]:
    """Suspend the tenant read filter for one scoped read.

    Used ONLY by ``routers.deps.load_student_for_tenant``, which immediately
    applies the same predicate explicitly (and raises the documented 403
    ``other_school`` when the pre-image exists outside the tenant). Any other
    use is a bug: it reopens the read hole this module exists to close.
    """
    previous = session.info.get(_TENANT_FILTER_BYPASS_KEY)
    session.info[_TENANT_FILTER_BYPASS_KEY] = True
    try:
        yield
    finally:
        if previous is None:
            session.info.pop(_TENANT_FILTER_BYPASS_KEY, None)
        else:  # pragma: no cover - nested use is not expected
            session.info[_TENANT_FILTER_BYPASS_KEY] = previous


def set_tenant_context(session: Session, school_id: int | None) -> None:
    """Attach (or clear) the tenant for the remainder of this session's life.

    ``None`` means "unscoped": admin, student and parent sessions, and every
    session that never authenticated (jobs, CLIs, tests) -- no filter is
    applied, which is the previous behaviour.
    """
    if school_id is None:
        session.info.pop(TENANT_SCHOOL_ID_KEY, None)
    else:
        session.info[TENANT_SCHOOL_ID_KEY] = int(school_id)


def tenant_school_id(session: Session) -> int | None:
    value = session.info.get(TENANT_SCHOOL_ID_KEY)
    return int(value) if isinstance(value, int) else None


def _school_student_id_subquery(school_id: int):
    """The student-id set of one school (mirrors ``_school_student_id_set``)."""
    return (
        select(ClassStudent.student_id)
        .join(ClassRoom, ClassRoom.id == ClassStudent.classroom_id)
        .where(ClassRoom.school_id == school_id)
    )


def _criteria_for(model: type, school_id: int):
    """The loader criterion for one anchor model at a given tenant."""
    if model is ClassRoom:
        return ClassRoom.school_id == school_id
    if model is ClassStudent:
        return ClassStudent.student_id.in_(_school_student_id_subquery(school_id))
    if model is Student:
        return Student.id.in_(_school_student_id_subquery(school_id))
    raise AssertionError(f"no tenancy criterion registered for {model!r}")


#: The anchor models the filter rewrites. Extend with a criterion above.
TENANT_ANCHOR_MODELS: tuple[type, ...] = (ClassRoom, ClassStudent, Student)


def _apply_tenant_criteria(statement: Any, school_id: int) -> Any:
    options = [
        with_loader_criteria(model, _criteria_for(model, school_id), include_aliases=True)
        for model in TENANT_ANCHOR_MODELS
    ]
    return statement.options(*options)


def install_tenant_filter(session_factory: sessionmaker[Session]) -> None:
    """Register the read-path filter on one session factory.

    Idempotent per factory (a second call is a no-op), so app creation and
    tests that build several factories cannot stack listeners. The listener
    rewrites ORM ``select()`` statements only; raw SQL, Core table selects
    and ``Session.get()`` pass through untouched (documented above).
    """
    if getattr(session_factory, "_bgpt_tenant_filter_installed", False):
        return
    session_factory._bgpt_tenant_filter_installed = True  # type: ignore[attr-defined]

    @event.listens_for(session_factory, "do_orm_execute")
    def _tenant_read_filter(state: Any) -> None:
        if state.session.info.get(_TENANT_FILTER_BYPASS_KEY):
            return
        school_id = state.session.info.get(TENANT_SCHOOL_ID_KEY)
        if not isinstance(school_id, int):
            return
        if not state.is_select or state.is_column_load or state.is_relationship_load:
            # Column/relationship loads inherit the parent statement's
            # criteria; re-applying would be redundant work.
            return
        state.statement = _apply_tenant_criteria(state.statement, school_id)
