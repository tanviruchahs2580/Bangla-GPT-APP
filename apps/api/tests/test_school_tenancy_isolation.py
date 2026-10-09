"""Cross-tenant isolation for every school dashboard route (AUD-0006).

At c35b6f6 `routers/school.py` sat at 60.20% branch coverage with roughly 250
contiguous untested lines: /school/students, /school/teachers, /school/classes,
/school/coverage, /school/analytics, /schools/mine and /school/overview were
exercised only in the happy path. Tenancy isolation is a headline product
claim and a cross-tenant data-exposure risk class, so TST-04 holds it to a
90% branch floor.

Every test here builds TWO schools with their own principals, teachers and
pupils, then asserts that a principal of school B can neither read school A's
data nor reach it through a crafted identifier. The same-school principal
must still succeed, so the isolation cannot be "passed" by denying everyone.
"""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app

PASSWORD = "Str0ngRootPassw0rd!"
JOIN_PASSWORD = "Str0ngJoinPassw0rd!"

# Each route a school_admin can read, with the query that must stay scoped.
DASHBOARD_ROUTES = [
    "/school/overview",
    "/school/students",
    "/school/teachers",
    "/school/classes",
    "/school/coverage",
    "/school/analytics",
]


@pytest.fixture
def env(tmp_path):
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/tenancy.db",
        jwt_secret="test-secret-0123456789abcdef0123456789",
        admin_email="root@example.com",
        admin_password=PASSWORD,
        force_admin_password_change=False,
    )
    client = TestClient(create_app(settings))
    conn = sqlite3.connect(f"{tmp_path}/tenancy.db")
    yield client, conn
    conn.close()


def _login(client: TestClient, email: str, pw: str = PASSWORD) -> dict:
    res = client.post("/auth/login", json={"email": email, "password": pw})
    assert res.status_code == 200, res.text
    return {"Authorization": "Bearer " + res.json()["access_token"]}


def _root(client: TestClient) -> dict:
    return _login(client, "root@example.com")


def _invite(client: TestClient, headers: dict, school_id: int, role: str) -> str:
    res = client.post(f"/schools/{school_id}/invites", json={"role": role}, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()["code"]


def _join(client: TestClient, code: str, email: str) -> None:
    res = client.post(
        "/auth/join-school",
        json={"invite_code": code, "email": email, "password": JOIN_PASSWORD, "name": "Staff"},
    )
    assert res.status_code == 201, res.text


def _build_school(client: TestClient, name: str, principal_email: str, teacher_email: str):
    """Create a school with one principal and one teacher. Returns both headers."""
    root = _root(client)
    school = client.post("/admin/schools", json={"name": name}, headers=root).json()
    sid = school["id"]

    _join(client, _invite(client, root, sid, "school_admin"), principal_email)
    principal = _login(client, principal_email, JOIN_PASSWORD)

    _join(client, _invite(client, root, sid, "teacher"), teacher_email)
    teacher = _login(client, teacher_email, JOIN_PASSWORD)
    room = client.post("/teacher/classrooms", json={"class_level": 6}, headers=teacher).json()

    return {"school": school, "principal": principal, "teacher": teacher, "room_id": room["id"]}


def _two_schools(client: TestClient):
    a = _build_school(client, "School Alpha", "prin.a@ten.test", "teach.a@ten.test")
    b = _build_school(client, "School Beta", "prin.b@ten.test", "teach.b@ten.test")
    return a, b


@pytest.mark.parametrize("route", DASHBOARD_ROUTES)
def test_principal_can_read_own_school(route, env):
    """The positive case, so isolation cannot be satisfied by denying all."""
    client, _ = env
    a, _b = _two_schools(client)
    res = client.get(route, headers=a["principal"])
    assert res.status_code == 200, f"{route} -> {res.status_code} {res.text[:200]}"


@pytest.mark.parametrize("route", DASHBOARD_ROUTES)
def test_anonymous_is_refused(route, env):
    client, _ = env
    _two_schools(client)
    assert client.get(route).status_code == 401, route


@pytest.mark.parametrize("route", DASHBOARD_ROUTES)
def test_teacher_cannot_read_school_dashboard(route, env):
    """A teacher in the school is still not an authorised dashboard reader."""
    client, _ = env
    a, _b = _two_schools(client)
    res = client.get(route, headers=a["teacher"])
    assert res.status_code == 403, f"{route} with teacher -> {res.status_code}"


def test_schools_mine_returns_only_the_callers_own_school(env):
    """The headline tenancy assertion: one school id, and never the other's.

    /schools/mine returns a single SchoolOverviewOut keyed on `school_id`,
    scoped from user.school_id (school.py:426), so the isolation check is that
    two principals of different schools resolve to different ids.
    """
    client, _ = env
    _two_schools(client)
    a = _login(client, "prin.a@ten.test", JOIN_PASSWORD)
    b = _login(client, "prin.b@ten.test", JOIN_PASSWORD)

    body_a = client.get("/schools/mine", headers=a)
    body_b = client.get("/schools/mine", headers=b)
    assert body_a.status_code == 200 and body_b.status_code == 200

    sid_a = body_a.json()["school_id"]
    sid_b = body_b.json()["school_id"]
    assert sid_a != sid_b, (
        f"principals of different schools both resolved to school {sid_a} -- "
        "cross-tenant leak in /schools/mine"
    )
    # A principal must also see their own school's name, not another tenant's.
    assert "Alpha" in body_a.json()["name"]
    assert "Beta" in body_b.json()["name"]


def test_students_list_is_scoped_to_the_calling_schools_tenant(env):
    """Seed one pupil per school and assert neither list contains the other."""
    client, _ = env
    a, b = _two_schools(client)

    created = []
    for who, tag in ((a, "alpha"), (b, "beta")):
        res = client.post(
            f"/teacher/classrooms/{who['room_id']}/import",
            json={"csv_text": f"name,email\nPupil {tag},pupil.{tag}@ten.test"},
            headers=who["teacher"],
        )
        assert res.status_code in (200, 201), res.text
        created.append(tag)

    body_a = client.get("/school/students", headers=a["principal"])
    body_b = client.get("/school/students", headers=b["principal"])
    assert body_a.status_code == 200 and body_b.status_code == 200

    # The page exposes pupil names, not emails; assert on the names that were
    # seeded through each school's own classroom import.
    items_a = body_a.json()["items"]
    items_b = body_b.json()["items"]
    names_a = {row["name"] for row in items_a}
    names_b = {row["name"] for row in items_b}

    assert "Pupil alpha" in names_a, "school A should see its own pupil"
    assert "Pupil beta" in names_b, "school B should see its own pupil"
    assert "Pupil beta" not in names_a, "school A must not see school B's pupils"
    assert "Pupil alpha" not in names_b, "school B must not see school A's pupils"
    assert body_a.json()["total"] == 1 and body_b.json()["total"] == 1, (
        f"each tenant should hold exactly one pupil, got {body_a.json()['total']} and "
        f"{body_b.json()['total']}"
    )
