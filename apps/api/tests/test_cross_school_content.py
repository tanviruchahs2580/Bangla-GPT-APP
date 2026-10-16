"""S-007: the shared chapter-content library is read-shared, write-scoped.

The audit proved (``probe_content_xschool``) that a teacher of school B could
append the new "current" version of chapter content authored by school A's
teacher, and every school then read B's overwrite. These tests pin the fix:

* school B's PUT (and AI generate) on school A's content is 403 with the
  stable ``content_read_only`` code, and A's content is byte-identical after;
* school A's own teacher -- including a second teacher of the same school --
  can still append a version;
* platform-seeded content (``created_by`` NULL) is read-only for teachers;
* every school can still READ the shared current version.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.models import ChapterContent
from bangla_gpt_api.db.session import make_engine, make_session_factory
from bangla_gpt_api.main import create_app

PASSWORD = "supersecret1"
JWT = "test-secret-0123456789abcdef0123456789"

# A real chapter of the bundled class-6 science corpus, so the mock provider
# can draft content without a network call.
CHAPTER = "কোষ"


@pytest.fixture
def client(tmp_path) -> TestClient:
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/xschool.db",
        jwt_secret=JWT,
        admin_email="root@example.com",
        admin_password=PASSWORD,
        force_admin_password_change=False,
    )
    return TestClient(create_app(settings))


def _login(client: TestClient, email: str) -> dict:
    res = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _school_teacher(client: TestClient, admin: dict, tag: str) -> dict:
    """Create a school with one teacher and return that teacher's headers."""
    school = client.post("/admin/schools", json={"name": f"School {tag}"}, headers=admin)
    assert school.status_code == 201, school.text
    invite = client.post(
        f"/schools/{school.json()['id']}/invites",
        json={"role": "teacher"},
        headers=admin,
    )
    assert invite.status_code == 201, invite.text
    email = f"teacher-{tag.lower()}@example.test"
    joined = client.post(
        "/auth/join-school",
        json={
            "invite_code": invite.json()["code"],
            "email": email,
            "password": PASSWORD,
            "name": f"Teacher {tag}",
        },
    )
    assert joined.status_code == 201, joined.text
    return _login(client, email)


def _generate(client: TestClient, headers: dict) -> dict:
    res = client.post(
        "/teacher/content/generate",
        json={"class_level": 6, "subject": "science", "chapter": CHAPTER},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    return res.json()


def _get(client: TestClient, headers: dict) -> dict:
    res = client.get(
        "/teacher/content",
        params={"class_level": 6, "subject": "science", "chapter": CHAPTER},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    return res.json()


def _edit_body(summary: str) -> dict:
    return {
        "class_level": 6,
        "subject": "science",
        "chapter": CHAPTER,
        "sections": {
            "summary": summary,
            "notes": "n",
            "key_points": ["k"],
            "examples": ["e"],
            "practice_qs": ["p"],
            "homework": ["h"],
            "exam_tips": ["t"],
        },
    }


@pytest.fixture
def two_schools(client: TestClient) -> dict:
    admin = _login(client, "root@example.com")
    return {
        "A": _school_teacher(client, admin, "A"),
        "B": _school_teacher(client, admin, "B"),
    }


def test_other_school_cannot_overwrite_authored_content(client, two_schools) -> None:
    authored = _generate(client, two_schools["A"])
    assert authored["version"] == 1
    assert authored["source"] == "ai"

    # Shared-read design is preserved: school B reads the same current version.
    read_by_b = _get(client, two_schools["B"])
    assert read_by_b["version"] == 1
    assert read_by_b["sections"] == authored["sections"]

    # The write across the tenancy wall is refused, explicitly and coded.
    put = client.put(
        "/teacher/content", json=_edit_body("B-authored overwrite"), headers=two_schools["B"]
    )
    assert put.status_code == 403, put.text
    assert put.json()["detail"]["code"] == "content_read_only"

    # And the AI-generate append path is refused too (same library write),
    # before any provider call could produce a version.
    gen = client.post(
        "/teacher/content/generate",
        json={"class_level": 6, "subject": "science", "chapter": CHAPTER},
        headers=two_schools["B"],
    )
    assert gen.status_code == 403, gen.text
    assert gen.json()["detail"]["code"] == "content_read_only"

    # School A's content is unchanged: same version, same bytes.
    after = _get(client, two_schools["A"])
    assert after["version"] == 1
    assert after["sections"] == authored["sections"]


def test_own_school_can_still_append_a_version(client, two_schools) -> None:
    _generate(client, two_schools["A"])

    edited = client.put("/teacher/content", json=_edit_body("A-edit"), headers=two_schools["A"])
    assert edited.status_code == 200, edited.text
    assert edited.json()["version"] == 2
    assert edited.json()["source"] == "teacher"

    current = _get(client, two_schools["A"])
    assert current["version"] == 2
    assert current["sections"]["summary"] == "A-edit"
    assert current["sections"] == _edit_body("A-edit")["sections"]


def test_second_teacher_of_the_same_school_may_edit(client, two_schools) -> None:
    """The guard is the tenancy, not the single author account."""
    _generate(client, two_schools["A"])
    admin = _login(client, "root@example.com")
    schools = client.get("/admin/schools", headers=admin).json()
    school_a = next(s for s in schools if s["name"] == "School A")
    invite = client.post(
        f"/schools/{school_a['id']}/invites", json={"role": "teacher"}, headers=admin
    )
    assert invite.status_code == 201, invite.text
    assert (
        client.post(
            "/auth/join-school",
            json={
                "invite_code": invite.json()["code"],
                "email": "teacher-a2@example.test",
                "password": PASSWORD,
                "name": "Teacher A2",
            },
        ).status_code
        == 201
    )
    headers = _login(client, "teacher-a2@example.test")
    res = client.put("/teacher/content", json=_edit_body("A2-edit"), headers=headers)
    assert res.status_code == 200, res.text
    assert res.json()["version"] == 2


def test_platform_seeded_content_is_read_only_for_teachers(client, two_schools, tmp_path) -> None:
    """``created_by`` NULL means no tenancy to match -> read-only."""
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/xschool.db",
        jwt_secret=JWT,
    )
    engine = make_engine(settings)
    factory = make_session_factory(engine)
    with factory() as db:
        db.add(
            ChapterContent(
                subject="science",
                class_level=6,
                chapter=CHAPTER,
                version=1,
                source="ai",
                payload={
                    "summary": "platform-seed",
                    "notes": "n",
                    "key_points": ["k"],
                    "examples": ["e"],
                    "practice_qs": ["p"],
                    "homework": ["h"],
                    "exam_tips": ["t"],
                },
                created_by=None,
            )
        )
        db.commit()
    with factory() as db:
        assert db.execute(select(ChapterContent)).scalars().one().created_by is None

    put = client.put("/teacher/content", json=_edit_body("takeover"), headers=two_schools["A"])
    assert put.status_code == 403, put.text
    assert put.json()["detail"]["code"] == "content_read_only"
    # still readable
    assert _get(client, two_schools["A"])["sections"]["summary"] == "platform-seed"
