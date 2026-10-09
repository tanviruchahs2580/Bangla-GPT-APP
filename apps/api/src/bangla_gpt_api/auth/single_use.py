"""Atomic claiming of single-use artefacts (verification, reset, invite codes).

Every one of these rows carries ``token_hash``/``code_hash`` plus a
``used_at`` marker. The tempting implementation is

    row = SELECT ... WHERE code_hash = :h AND used_at IS NULL
    row.used_at = now

which is check-then-act. Two requests carrying the same code can both observe
``used_at IS NULL``, both pass the guard, and both redeem it. For a password
reset that means an interceptor and the legitimate user can both set the
credential; for an invite code it means one code creates two accounts.

The fix is a single conditional UPDATE. The database does the compare-and-set,
so the loser matches zero rows instead of re-reading stale state:

    UPDATE <table> SET used_at = :now
     WHERE <hash_col> = :h AND used_at IS NULL AND expires_at >= :now

``rowcount == 1`` means this caller won the claim; anything else means the code
was already spent or expired and the caller must reject it. Under READ
COMMITTED the winning row is locked for the rest of the transaction, so a
concurrent claimant blocks and then re-evaluates the predicate against the
committed value rather than the value it snapshotted.

Expiry lives in the WHERE clause rather than a Python comparison so that an
expired code and an already-used code are rejected identically, with no second
read to get out of step with the claim.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from sqlalchemy import ColumnElement, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session


def claim_single_use(
    db: Session,
    model: Any,
    *,
    hash_column: Any,
    hash_value: str,
    now: datetime,
    require_unexpired: bool = True,
    extra_condition: ColumnElement[bool] | None = None,
) -> bool:
    """Try to consume a single-use row. Returns True only for the winner.

    ``True`` means this call transitioned ``used_at`` from NULL to ``now``;
    ``False`` means the code was unknown, already used, or expired. Callers
    must treat ``False`` as a rejection and must not fall back to a plain
    SELECT, or the race returns.

    ``model`` is a declarative class (``EmailVerification``, ``PasswordReset``,
    the invite models). It is typed loosely because it is consumed through
    mapped attributes that no static protocol describes; the WHERE clause
    itself is what enforces correctness.

    ``require_unexpired=False`` is for ``SchoolInvite``, which has no
    ``expires_at`` column at all -- its codes are single-use but never
    time-limited. Passing True there raises AttributeError, which is the
    intended loud failure rather than a silently dropped expiry check.
    """
    conditions = [hash_column == hash_value, model.used_at.is_(None)]
    if require_unexpired:
        conditions.append(model.expires_at >= now)
    stmt = update(model).where(*conditions).values(used_at=now)
    if extra_condition is not None:
        stmt = stmt.where(extra_condition)
    result = cast(CursorResult, db.execute(stmt))
    return result.rowcount == 1


def fetch_by_hash(db: Session, model: Any, *, hash_column: Any, hash_value: str) -> Any:
    """Read a single-use row after :func:`claim_single_use` returned True.

    Kept separate from the claim so the UPDATE stays a single conditional
    statement that the database can arbitrate, and so this stays portable to
    SQLite, which only gained RETURNING in 3.35.
    """
    from sqlalchemy import select

    return db.execute(select(model).where(hash_column == hash_value)).scalar_one_or_none()
