"""BC-5 (T-20): dual-write + read plumbing for the attempt-membership links.

The JSON ``attempts`` arrays on ``assignments`` / ``short_tests`` stay the
DEFAULT read path; this module is the seam the link tables are reached
through:

* :func:`sync_attempt_links` mirrors the JSON list into the link table inside
  the caller's transaction (dual-write — a rollback of either write rolls
  back both, because they share the session);
* :func:`attempt_refs` reads back either the JSON list (default) or the link
  table (``ATTEMPT_LINKS_READ=true``), always as the same
  ``[(student_id, attempt_id)]`` shape, so the API responses are identical
  under both settings;
* :func:`reconcile_attempt_links` reports count and set equality between the
  two stores — the expand/contract check that must pass before the JSON read
  default flips (S-3) and the JSON column drops (later release).

``assignment`` reads the EXISTING ``assignment_recipients`` mirror (migration
c5d7e9f1a3b5 created and backfilled it); a second assignment link table
would be a duplicate.
"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from bangla_gpt_api.db.models import (
    Assignment,
    AssignmentRecipient,
    ShortTest,
    ShortTestAttemptLink,
)

Refs = list[tuple[int, int]]

_LINKS: dict[str, tuple[type[AssignmentRecipient] | type[ShortTestAttemptLink], str]] = {
    "assignment": (AssignmentRecipient, "assignment_id"),
    "short_test": (ShortTestAttemptLink, "short_test_id"),
}


def _link_info(kind: str) -> tuple[type[AssignmentRecipient] | type[ShortTestAttemptLink], str]:
    try:
        return _LINKS[kind]
    except KeyError:
        raise ValueError(f"unknown attempt-link kind: {kind!r}") from None


def sync_attempt_links(db: Session, *, kind: str, parent_id: int, refs: Refs) -> None:
    """Mirror ``refs`` into the link table for one parent, in-transaction.

    Called right after the JSON list is written. Existing rows for the parent
    are replaced (the JSON list is the source of truth for membership shape),
    so re-running the create path can never duplicate rows thanks to the
    unique (parent, student) constraint.
    """
    link_cls, parent_fk = _link_info(kind)
    db.execute(delete(link_cls).where(getattr(link_cls, parent_fk) == parent_id))
    for sid, aid in refs:
        db.add(link_cls(**{parent_fk: parent_id, "student_id": sid, "attempt_id": aid}))


def attempt_refs(
    db: Session, *, kind: str, parent: Assignment | ShortTest, links_read: bool
) -> Refs:
    """The (student_id, attempt_id) refs for one parent, from either store."""
    link_cls, parent_fk = _link_info(kind)
    if not links_read:
        raw = parent.attempts or []
        out: Refs = []
        for entry in raw:
            try:
                out.append((int(entry["student_id"]), int(entry["attempt_id"])))
            except (KeyError, TypeError, ValueError):
                continue
        return out
    rows = db.execute(
        select(
            link_cls.student_id,
            link_cls.attempt_id,
        )
        .where(getattr(link_cls, parent_fk) == parent.id)
        .order_by(link_cls.student_id)
    ).all()
    return [(int(s), int(a)) for s, a in rows]


def reconcile_attempt_links(db: Session, *, kind: str) -> dict:
    """Count + set equality between the JSON array and the link table.

    The expand/contract gate: both stores must agree per parent before the
    JSON read default flips.
    """
    link_cls, parent_fk = _link_info(kind)
    parents: list[Assignment | ShortTest]
    if kind == "assignment":
        parents = list(db.execute(select(Assignment)).scalars().all())
    else:
        parents = list(db.execute(select(ShortTest)).scalars().all())
    mismatches: list[dict] = []
    for parent in parents:
        json_refs = set(attempt_refs(db, kind=kind, parent=parent, links_read=False))
        link_rows = db.execute(
            select(
                link_cls.student_id,
                link_cls.attempt_id,
            ).where(getattr(link_cls, parent_fk) == parent.id)
        ).all()
        link_refs = {(int(s), int(a)) for s, a in link_rows}
        if json_refs != link_refs or len(link_rows) != len(json_refs):
            mismatches.append(
                {
                    "id": parent.id,
                    "json": sorted(json_refs),
                    "links": sorted(link_refs),
                }
            )
    return {
        "kind": kind,
        "parents": len(parents),
        "mismatched": len(mismatches),
        "mismatches": mismatches[:10],
    }
