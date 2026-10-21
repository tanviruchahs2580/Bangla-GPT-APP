"""SQLAlchemy models: base (split out of db/models.py, C-03)."""

from __future__ import annotations

from datetime import UTC, datetime


def _utcnow() -> datetime:
    return datetime.now(UTC)
