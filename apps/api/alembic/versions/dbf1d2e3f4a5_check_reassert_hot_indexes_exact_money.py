"""DB-FIX-001..004: re-assert two invariants, index four hot paths, exact money

Revision ID: dbf1d2e3f4a5
Revises: e4b8c0d2f6a8
Create Date: 2026-11-10

Four verified schema defects from the 2026-11-10 schema review. This is a NEW
revision on purpose: a3c5e7f9b1d3 was already amended in place once (8c12758
shipped it with ``ck_answer_log_chosen`` = ``chosen >= 0``; 08b6ee5 edited the
same file to ``chosen BETWEEN -1 AND 7`` after it had been applied in
environments -- docs/runbook.md section 7 forbids exactly that), so nothing
here touches an applied revision. The consequence of that in-place edit is
DB-FIX-001: a database that applied the earlier definition still carries
``chosen >= 0`` while ``alembic_version`` marks a3c5e7f9b1d3 as applied, so no
upgrade ever revisits it. Only a new revision can converge those databases.

**DB-FIX-001 -- ``ck_answer_log_chosen``, re-asserted idempotently.**
``chosen = -1`` means "I did not answer" and is part of the API contract
(``schemas.py:494`` ``Field(ge=-1, le=7)``, read at ``routers/learn.py:603``;
the ORM declares the same bounds at ``db/models.py:213-214``). A database that
applied the pre-08b6ee5 definition has ``CHECK (chosen >= 0)``: every skipped
question then fails its insert with an IntegrityError, and the database never
self-heals.

* PostgreSQL: ``DROP CONSTRAINT IF EXISTS`` then ``ADD CONSTRAINT``
  (``a3c5e7f9b1d3:97`` carries the intended condition). ADD CONSTRAINT
  validates every existing row under **ACCESS EXCLUSIVE** on ``answer_log`` --
  the fastest-growing table in the schema (one row per answered question,
  retention 730 days: ``services/retention.py:118``, ``:155``; the largest
  table by row count in the deployed shape). **This needs a deploy window and
  a stated row count** -- measure it first:
  ``SELECT count(*) FROM answer_log``. Find a violating row (which aborts the
  migration loudly rather than passing silently) with
  ``SELECT id FROM answer_log WHERE chosen < -1 OR chosen > 7``. If the count
  is large, the runbook's NOT VALID + separate VALIDATE CONSTRAINT two-step is
  the smaller-lock form; this revision ships the plain two-statement form the
  review asked for. Both statements run in one transaction, so a failed
  validation rolls back whole -- there is no window where the constraint is
  absent.
* SQLite: a CHECK is baked into the table DDL and cannot be altered, so the
  re-assert is an alembic batch-mode table rebuild (copy-and-move): O(table
  rows) on ``answer_log``, temporary double storage, and the indexes are
  re-created afterwards. The rebuild is **guarded**: the stored CREATE TABLE
  is read first and the rebuild is skipped when it already carries the
  intended predicate, so a database that took the corrected a3c5e7f9b1d3 (and
  every database this revision has already run against) pays nothing. A
  predicate spelled differently but semantically equivalent does not exist in
  this chain today; if one appears, it costs a rebuild -- never a wrong
  constraint.

**DB-FIX-002 -- ``ck_ai_jobs_attempts``, created.**
Declared in the ORM at ``db/models.py:1143-1144`` and created by no migration:
the ``_CHECKS`` map in ``a3c5e7f9b1d3`` carries only ``ck_ai_jobs_status`` for
``ai_jobs``, and ``d2f6a8c0b4e1:43-46`` added the ``attempts`` column without a
check (none of the on-disk SQLite databases has it; the migrated schema had 54
CHECKs and not this one). Same two engine paths and the same guard as
DB-FIX-001, condition copied verbatim from the model (``attempts >= 0``).
The ADD CONSTRAINT cannot fail validation on existing data: ``attempts`` is
NOT NULL with ``server_default '0'`` (``db/models.py:1180``), so no row can be
negative.

**DB-FIX-003 -- four missing indexes on the slowest paths.**
Single-column vs composite chosen per query shape, not per column:

* ``ix_chat_messages_created_at`` (single) -- the nightly sweep ages turns on
  their own timestamp (``services/retention.py:71``, counted at ``:133``) and
  the refusal audit filters ``created_at >= cutoff``
  (``routers/admin.py:391``). Only ``ix_chat_messages_conversation_id``
  existed, so both were a full scan of the largest table. Both predicates are
  a plain range on one column, with no second predicate to fold in.
* ``ix_conversations_created_at`` (single) -- same shape for the emptied-thread
  sweep (``services/retention.py:98``, ``:133``); the correlated EXISTS inside
  it filters ``chat_messages``, which the index above now serves.
* ``ix_ai_jobs_status_updated`` (composite ``status, updated_at``) --
  ``_delete_by_id_batches`` re-issues
  ``status IN ('ready','failed') AND updated_at < cutoff LIMIT 5000`` once per
  batch (``services/retention.py:255-260``; ``TERMINAL_STATUSES`` is defined at
  ``jobs.py:59``). The composite is chosen over a single-column
  ``updated_at`` index because the predicate is an equality/IN prefix plus a
  range on the second column: the index satisfies BOTH terms and the LIMIT can
  stop after 5000 index entries, whereas ``updated_at`` alone would find the
  same candidate rows but force a table lookup per candidate to test
  ``status``. Only 2 of 5 status values are terminal, so the prefix actually
  filters. Not extended to ``(status, updated_at, id)``: the delete still
  needs the row, so covering ``id`` buys nothing.
* ``ix_assignment_recipients_attempt_id`` (single) -- the only one of the 52
  foreign keys (``c4d8e0f2a6b9``) with no supporting index. Account erasure
  deletes every attempt of a student (``services/gdpr.py:904``) and PostgreSQL
  must check the child table per deleted parent row; without the index that is
  a full scan of ``assignment_recipients`` for every attempt on the
  data-subject path. Single column, because the query is a plain FK lookup.

All four are additive on both engines (CREATE INDEX / DROP INDEX, no table
rebuild) and cost one b-tree write per insert on their table. They are created
last, after the batch rebuilds above, so no rebuild has to carry them.

**DB-FIX-004 -- ``ai_usage.estimated_cost_usd`` becomes exact.**
``db/models.py:1244`` declared ``Float``: a monthly budget decided by repeated
binary-float addition is not reproducible
(``services/costs.py::month_cost_usd`` sums the column at ``:227``;
``check_ai_budget`` compares the sum against the cap at ``:242``).
Precision/scale: ``Numeric(14, 10)``. Scale 10 matches the writer's own
granularity -- ``estimate_cost_usd`` rounds to 10 decimal places
(``services/costs.py:99``) and the smallest real charge is ~1.9e-06 USD (25
estimated tokens on the cheapest model at 0.000075 USD/1K: ``costs.py:37``),
so 6 decimal places would round a single small request to 2e-06 and bias the
sum; 10 keeps exactly what the writer intends to store. Precision 14 leaves 4
integer digits for the per-row ledger value (a single generation cannot
approach USD 10,000). The column keeps its NOT NULL and its
``estimated_cost_usd >= 0`` check (``db/models.py:1213-1215``).

**SQLite caveat, stated honestly:** SQLite has NUMERIC affinity, not a decimal
type. The DDL below declares NUMERIC(14, 10) and new values are stored with
that affinity, but SQLite stores them as REAL internally, so *exactness is a
PostgreSQL guarantee only*; on SQLite the column is a documented declaration.
What this change buys on both engines is that a PostgreSQL deployment -- the
production shape -- stops accumulating binary-float error: the ledger rows and
the monthly SUM() are decimal arithmetic, and the model's ``asdecimal=False``
(db/models.py:1244) converts the exact total once at the Python boundary,
which is why no reader in ``services/costs.py``, ``routers/admin.py`` or
``services/gdpr.py`` changes type and ``mypy src`` gains no new error.
Completing the guarantee end-to-end would mean a Decimal-typed
``month_cost_usd``/``estimate_cost_usd`` in ``services/costs.py`` -- a
follow-up for that file's owner, not this revision's file scope.

**Reversibility.** Every change is reversed by ``downgrade()`` except
DB-FIX-001, which is deliberately a no-op for the bounds: the state it would
"restore" is the bug (``chosen >= 0`` rejects the API's own -1 sentinel), and a
downgrade must never reintroduce a defect that bricks skipped-question inserts.
The downgrade drops the four indexes, drops ``ck_ai_jobs_attempts`` (restoring
the exact pre-revision schema), and returns the cost column to ``Float`` --
which loses nothing further, because the up-conversion already rounded each
value to 10 decimal places.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "dbf1d2e3f4a5"
down_revision: str | Sequence[str] | None = "e4b8c0d2f6a8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: DB-FIX-001: the bounds the API contract and the ORM already agree on
#: (schemas.py:494, db/models.py:211-214, a3c5e7f9b1d3:97).
_CHOSEN_CHECK = "ck_answer_log_chosen"
_CHOSEN_CONDITION = "chosen BETWEEN -1 AND 7"

#: DB-FIX-002: copied verbatim from db/models.py:1143-1144.
_ATTEMPTS_CHECK = "ck_ai_jobs_attempts"
_ATTEMPTS_CONDITION = "attempts >= 0"

#: DB-FIX-003: (index name, table, columns) -- rationale per index in the
#: module docstring against the query that needs it.
_ADDED_INDEXES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("ix_chat_messages_created_at", "chat_messages", ("created_at",)),
    ("ix_conversations_created_at", "conversations", ("created_at",)),
    ("ix_ai_jobs_status_updated", "ai_jobs", ("status", "updated_at")),
    ("ix_assignment_recipients_attempt_id", "assignment_recipients", ("attempt_id",)),
)

#: DB-FIX-004: the exact column that replaces Float (see the docstring).
_COST_TABLE = "ai_usage"
_COST_COLUMN = "estimated_cost_usd"
_COST_PRECISION = 14
_COST_SCALE = 10


def _postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _normalised(sql: str) -> str:
    return " ".join(sql.split()).casefold()


def _sqlite_table_ddl(table: str) -> str:
    """The stored CREATE TABLE for ``table`` (the only place a CHECK lives)."""
    row = op.get_bind().exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    if row is None or not row[0]:
        raise RuntimeError(f"{table}: table DDL not found")
    return str(row[0])


def _reassert_check(table: str, name: str, condition: str) -> None:
    """Idempotently force ``CONSTRAINT name CHECK (condition)`` to exist.

    PostgreSQL: drop-if-exists then add (one transactional pair; see the
    ACCESS EXCLUSIVE warning in the module docstring).

    SQLite: read the stored DDL and skip the rebuild when the intended
    predicate is already there; otherwise rebuild the table through batch
    mode, dropping the old definition only when the name exists (a name that
    is absent is a plain add).
    """
    if _postgres():
        op.execute(f'ALTER TABLE "{table}" DROP CONSTRAINT IF EXISTS "{name}"')
        op.create_check_constraint(name, table, condition)
        return

    ddl = _sqlite_table_ddl(table)
    if _normalised(condition) in _normalised(ddl):
        return  # already asserted -- no rebuild
    with op.batch_alter_table(table) as batch:
        if _normalised(name) in _normalised(ddl):
            batch.drop_constraint(name, type_="check")
        batch.create_check_constraint(name, condition)


def _drop_check_if_present(table: str, name: str) -> None:
    """Remove a CHECK this revision created, if the database carries it."""
    if _postgres():
        op.execute(f'ALTER TABLE "{table}" DROP CONSTRAINT IF EXISTS "{name}"')
        return
    ddl = _sqlite_table_ddl(table)
    if _normalised(name) not in _normalised(ddl):
        return
    with op.batch_alter_table(table) as batch:
        batch.drop_constraint(name, type_="check")


def _alter_cost_column(*, to_numeric: bool) -> None:
    """Swap the ledger column between Float and Numeric(14, 10)."""
    numeric = sa.Numeric(_COST_PRECISION, _COST_SCALE)
    from_type, to_type = (sa.Float(), numeric) if to_numeric else (numeric, sa.Float())
    if _postgres():
        kwargs: dict[str, str] = {}
        if to_numeric:
            # explicit cast: the rounding the up-conversion performs is
            # visible here instead of left to an implicit float -> numeric
            # cast. Not added in the other direction (numeric -> float needs
            # no cast to a narrower type, and casting back to numeric(14, 10)
            # there would say the wrong thing).
            kwargs["postgresql_using"] = (
                f"{_COST_COLUMN}::numeric({_COST_PRECISION}, {_COST_SCALE})"
            )
        op.alter_column(
            _COST_TABLE,
            _COST_COLUMN,
            existing_type=from_type,
            type_=to_type,
            existing_nullable=False,
            **kwargs,
        )
        return
    # SQLite cannot ALTER a column type: batch mode rebuilds the table
    # (copy-and-move). Its NUMERIC affinity is not a decimal type -- see the
    # caveat in the module docstring.
    with op.batch_alter_table(_COST_TABLE) as batch:
        batch.alter_column(
            _COST_COLUMN,
            existing_type=from_type,
            type_=to_type,
            existing_nullable=False,
        )


def upgrade() -> None:
    # 001/002 first: both may rebuild a table on SQLite, and the indexes added
    # below must not be carried through a rebuild.
    _reassert_check("answer_log", _CHOSEN_CHECK, _CHOSEN_CONDITION)
    _reassert_check("ai_jobs", _ATTEMPTS_CHECK, _ATTEMPTS_CONDITION)

    # 004: the type change (table rebuild on SQLite, rewrite on PostgreSQL).
    _alter_cost_column(to_numeric=True)

    # 003: additive on both engines; created after every rebuild above.
    for index_name, table, columns in _ADDED_INDEXES:
        op.create_index(index_name, table, list(columns))


def downgrade() -> None:
    # Reverse order of upgrade(). 003 first: pure performance, dropped back.
    for index_name, table, _columns in reversed(_ADDED_INDEXES):
        op.drop_index(index_name, table_name=table)

    # 004: back to the Float the chain declared before this revision. Loses
    # nothing further -- the up-conversion already rounded to 10 dp.
    _alter_cost_column(to_numeric=False)

    # 002: the check did not exist before this revision; dropping it restores
    # the exact pre-revision schema.
    _drop_check_if_present("ai_jobs", _ATTEMPTS_CHECK)

    # 001 is deliberately NOT reversed. The only state a reversal could
    # restore is CHECK (chosen >= 0) -- the bug this revision exists to fix:
    # it rejects chosen = -1, the API's own "I did not answer" sentinel
    # (schemas.py:494), and would break the revision-review route on a
    # downgraded database. The answer_log bounds therefore survive a
    # downgrade unchanged.
