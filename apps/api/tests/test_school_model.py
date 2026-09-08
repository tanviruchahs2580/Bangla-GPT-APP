"""S2.1: schools/classrooms tables, class_level backfill, migration reversibility."""

import os
import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from bangla_gpt_api.config import get_settings

API_ROOT = Path(__file__).resolve().parents[1]
PREV_HEAD = "e6f7a8b9c0d1"
NEW_HEAD = "f7a8b9c0d1e2"


def _alembic_cfg(db_path: Path) -> Config:
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
    get_settings.cache_clear()
    cfg = Config()
    cfg.set_main_option("script_location", str(API_ROOT / "alembic"))
    return cfg


def _tables(db_path: Path) -> set[str]:
    con = sqlite3.connect(db_path)
    try:
        rows = con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        return {r[0] for r in rows}
    finally:
        con.close()


@pytest.fixture()
def seeded_db(tmp_path):
    """DB at the PREVIOUS head with students in class 6 (x2) and class 7 (x1)."""
    db = tmp_path / "school_migration.db"
    cfg = _alembic_cfg(db)
    command.upgrade(cfg, PREV_HEAD)
    con = sqlite3.connect(db)
    con.executemany(
        "INSERT INTO students (name, class_level, created_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
        [("Stu A", 6), ("Stu B", 6), ("Stu C", 7)],
    )
    con.commit()
    con.close()
    yield db, cfg
    get_settings.cache_clear()


def test_upgrade_backfills_school_classrooms_and_enrollments(seeded_db) -> None:
    db, cfg = seeded_db
    command.upgrade(cfg, "head")
    con = sqlite3.connect(db)
    try:
        schools = con.execute("SELECT name, code FROM schools").fetchall()
        assert schools == [("Default School", "BGPT-DEFAULT")]
        rooms = dict(
            con.execute(
                "SELECT class_level, COUNT(*) FROM classrooms GROUP BY class_level"
            ).fetchall()
        )
        assert rooms == {6: 1, 7: 1}
        sections = {r[0] for r in con.execute("SELECT section FROM classrooms")}
        assert sections == {"GEN"}
        # each student linked to exactly one room, matching its own class_level
        rows = con.execute(
            "SELECT s.class_level, c.class_level, COUNT(*)"
            " FROM class_students cs"
            " JOIN students s ON s.id = cs.student_id"
            " JOIN classrooms c ON c.id = cs.classroom_id"
            " GROUP BY 1, 2"
        ).fetchall()
        assert rows == [(6, 6, 2), (7, 7, 1)]
    finally:
        con.close()


def test_migration_is_reversible_and_leaves_students_intact(seeded_db) -> None:
    db, cfg = seeded_db
    command.upgrade(cfg, "head")
    command.downgrade(cfg, PREV_HEAD)
    gone = {"schools", "classrooms", "class_students", "class_teachers"}
    assert not gone & _tables(db)
    con = sqlite3.connect(db)
    try:
        assert con.execute("SELECT COUNT(*) FROM students").fetchone()[0] == 3
    finally:
        con.close()
    # re-upgrade must succeed cleanly (idempotent head application)
    command.upgrade(cfg, "head")
    assert gone <= _tables(db)


def test_upgrade_on_empty_database_creates_no_backfill_rows(tmp_path) -> None:
    db = tmp_path / "fresh.db"
    cfg = _alembic_cfg(db)
    command.upgrade(cfg, "head")
    assert {"schools", "classrooms", "class_students", "class_teachers"} <= _tables(db)
    con = sqlite3.connect(db)
    try:
        assert con.execute("SELECT COUNT(*) FROM schools").fetchone()[0] == 0
    finally:
        con.close()


def test_unique_constraints_enforced(tmp_path) -> None:
    db = tmp_path / "fresh2.db"
    cfg = _alembic_cfg(db)
    command.upgrade(cfg, "head")
    con = sqlite3.connect(db)
    try:
        school_sql = "INSERT INTO schools (name, code, created_at) VALUES (?, ?, CURRENT_TIMESTAMP)"
        con.execute(school_sql, ("S1", "X1"))
        with pytest.raises(sqlite3.IntegrityError):
            con.execute(school_sql, ("S2", "X1"))
        con.rollback()
        con.execute(
            "INSERT INTO classrooms (school_id, class_level, section, created_at)"
            " VALUES (1, 6, 'GEN', CURRENT_TIMESTAMP)"
        )
        with pytest.raises(sqlite3.IntegrityError):
            con.execute(
                "INSERT INTO classrooms (school_id, class_level, section, created_at)"
                " VALUES (1, 6, 'GEN', CURRENT_TIMESTAMP)"
            )
    finally:
        con.close()
