"""Column types that make the stored instant unambiguous (AUD-HI-02 / H-14).

Every timestamp column in this schema used to be a plain ``DateTime`` ->
PostgreSQL ``timestamp without time zone``: the instant was only correct as
long as the *reader* also assumed UTC, and the app pinned that assumption
with a session option (``db/session.py``). That pin protects this process;
it does not protect a ``psql`` session, a BI tool, a backup restored on
another host or a future service.

:class:`UtcDateTime` upgrades the storage to a true ``timestamptz`` on
PostgreSQL while keeping the Python-facing contract unchanged:

* **bind** — an aware value is normalised to UTC; a naive value is *defined*
  to be UTC (the house contract, ``datetime.now(UTC).replace(tzinfo=None)``)
  and gets the UTC tzinfo attached before storage. PostgreSQL stores the
  instant (timestamptz); SQLite keeps its naive ISO-8601 text, because SQLite
  has no timestamp type and its date functions are UTC anyway.
* **result** — an aware value (what psycopg returns for a timestamptz) is
  normalised to UTC and returned naive, so the ~30 router/PDF/export sites
  that strip or compare naive values keep working unchanged and a
  flag-day rewrite of the request layer is not a precondition.

The consequence is stated plainly: the *database* stores an instant; the
*application* passes naive UTC values, exactly as it does today.
"""

from datetime import UTC, datetime

from sqlalchemy import DateTime
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator


class UtcDateTime(TypeDecorator[datetime]):
    """Store datetime as UTC-backed ``timestamptz``; load as naive UTC."""

    impl = DateTime
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect):  # noqa: ANN201 - dialect type
        if dialect.name == "postgresql":
            return dialect.type_descriptor(DateTime(timezone=True))
        return dialect.type_descriptor(DateTime(timezone=False))

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            # House contract: a naive value IS UTC (see db/types module doc).
            value = value.replace(tzinfo=UTC)
        value = value.astimezone(UTC)
        if dialect.name == "postgresql":
            return value
        return value.replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value
        return value.astimezone(UTC).replace(tzinfo=None)
