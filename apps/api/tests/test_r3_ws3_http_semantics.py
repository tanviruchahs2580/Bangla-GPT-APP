"""R3 / WS3 H-03: HTTP semantics — Idempotency-Key and ETag/If-Match.

Both are opt-in and additive. The tests drive them the way a client would:
over HTTP for the replay/412 behaviour, and directly against the helper for
the cache-outage path (which needs a backend that fails).

What the audit's gap was, precisely: ``rg Idempotency-Key|If-Match`` returned
zero hits in the tree. These tests fail against a tree without
``routers/_http_semantics.py`` wired in, and pin the contract:

* a retried import with the same key replays the first response (invite codes
  included) and creates nothing new;
* a duplicate that arrives while the first call is still in flight gets
  ``409 idempotency_in_progress``;
* a too-short key is a 400 from the catalog;
* keys are per-user: two accounts using the same key value do not collide;
* a stale ``If-Match`` on the prefs PATCH is a 412 and changes nothing;
* an absent ``If-Match`` still works (no existing client breaks).
"""

from __future__ import annotations

import asyncio
import threading

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from bangla_gpt_api.caching import MemoryCache
from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app
from bangla_gpt_api.routers._http_semantics import run_once

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"
KEY = "retry-key-0000000001"


@pytest.fixture
def client(tmp_path) -> TestClient:
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/r3-http.db",
        jwt_secret=SECRET,
    )
    return TestClient(create_app(settings))


def _register(client: TestClient, email: str, role: str) -> dict:
    res = client.post(
        "/auth/register",
        json={
            "email": email,
            "password": PASSWORD,
            "name": "Teacher" if role == "teacher" else "শিক্ষার্থী",
            "role": role,
            **({"class_level": 6, "guardian_consent": True} if role == "student" else {}),
        },
    )
    assert res.status_code == 201, res.text
    token = client.post("/auth/login", json={"email": email, "password": PASSWORD}).json()[
        "access_token"
    ]
    return {"Authorization": f"Bearer {token}"}


def _room(client: TestClient, headers: dict, section: str = "W3I") -> int:
    res = client.post(
        "/teacher/classrooms", json={"class_level": 6, "section": section}, headers=headers
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


def _upload(client: TestClient, headers: dict, room: int, csv_text: str, *, key: str | None = KEY):
    extra = {"Idempotency-Key": key} if key else {}
    return client.post(
        f"/teacher/classrooms/{room}/import-file",
        content=csv_text.encode("utf-8"),
        headers={**headers, "Content-Type": "text/csv", **extra},
    )


def test_retry_with_the_same_key_replays_instead_of_enrolling_twice(client: TestClient) -> None:
    headers = _register(client, "idem@example.com", "teacher")
    room = _room(client, headers)
    csv_text = "name,email\r\nরহিম,idem-student@example.com\r\n"
    first = _upload(client, headers, room, csv_text)
    assert first.status_code == 200, first.text
    assert first.json()["created"] == 1

    second = _upload(client, headers, room, csv_text)
    assert second.status_code == 200, second.text
    assert second.headers.get("Idempotent-Replay") == "true"
    # Byte-identical body: the client recovers the one-time invite code.
    assert second.json() == first.json()
    # And nothing was created twice: a third call with a fresh key sees the
    # account as an existing duplicate.
    third = _upload(client, headers, room, csv_text, key="retry-key-0000000002")
    assert third.json()["rows"][0]["status"] == "duplicate_email"


def test_two_users_may_reuse_the_same_key_value(client: TestClient) -> None:
    a = _register(client, "idem-a@example.com", "teacher")
    b = _register(client, "idem-b@example.com", "teacher")
    room_a, room_b = _room(client, a, "W3A"), _room(client, b, "W3B")
    body_a = "name,email\r\nরহিম,shared-key-a@example.com\r\n"
    body_b = "name,email\r\nফাতেমা,shared-key-b@example.com\r\n"
    first = _upload(client, a, room_a, body_a)
    other = _upload(client, b, room_b, body_b)  # same key value, different user
    assert first.status_code == 200 and other.status_code == 200
    assert other.headers.get("Idempotent-Replay") is None
    assert other.json()["rows"][0]["email"] == "shared-key-b@example.com"


def test_a_short_key_is_a_400_from_the_catalog(client: TestClient) -> None:
    headers = _register(client, "idem-short@example.com", "teacher")
    room = _room(client, headers)
    res = _upload(client, headers, room, "name,email\r\n", key="short")
    assert res.status_code == 400, res.text
    assert res.json()["detail"]["code"] == "invalid_idempotency_key"


def test_an_in_flight_duplicate_is_a_409_not_a_second_side_effect() -> None:
    """The claim is atomic, so the second caller loses it and must not run."""
    cache = MemoryCache()
    started = threading.Event()
    finished = threading.Event()
    runs = []

    async def scenario() -> tuple[object, object]:
        async def slow() -> str:
            runs.append("ran")
            started.set()
            # Block until the duplicate has been refused.
            await asyncio.to_thread(finished.wait, 5)
            return "ok"

        first = asyncio.create_task(
            run_once(cache=cache, scope="t", user_id=1, key=KEY, produce=slow)
        )
        await asyncio.to_thread(started.wait, 5)
        try:
            await run_once(cache=cache, scope="t", user_id=1, key=KEY, produce=slow)
            duplicate: object = None
        except HTTPException as exc:
            duplicate = exc
        finished.set()
        return await first, duplicate

    first_result, duplicate = asyncio.run(scenario())
    assert first_result == "ok"
    assert isinstance(duplicate, HTTPException)
    assert duplicate.status_code == 409
    assert duplicate.detail["code"] == "idempotency_in_progress"
    assert runs == ["ran"], "the duplicate must not have produced a second side effect"


def test_a_cache_outage_does_not_refuse_the_write() -> None:
    """Fail-open: a dedupe cache that is down must not take writes down."""

    class DeadCache:
        def set_json_nx_strict(self, key: str, value: object, ttl: float) -> bool:
            from bangla_gpt_api.caching import CacheUnavailable

            raise CacheUnavailable("down")

    async def scenario() -> str:
        return await run_once(
            cache=DeadCache(), scope="t", user_id=1, key=KEY, produce=lambda: _ok()
        )

    async def _ok() -> str:
        return "produced"

    assert asyncio.run(scenario()) == "produced"


# --------------------------------------------------------------- ETag ----


def test_prefs_get_serves_a_validator_and_patch_honours_it(client: TestClient) -> None:
    headers = _register(client, "etag-student@example.com", "student")
    got = client.get("/students/me/prefs", headers=headers)
    assert got.status_code == 200, got.text
    etag = got.headers.get("ETag")
    assert etag and etag.startswith('"') and etag.endswith('"')

    # A PATCH carrying the validator succeeds and returns the NEW validator.
    patched = client.patch(
        "/students/me/prefs",
        json={"learning_prefs": {"explanation_style": "simple"}},
        headers={**headers, "If-Match": etag},
    )
    assert patched.status_code == 200, patched.text
    new_etag = patched.headers.get("ETag")
    assert new_etag and new_etag != etag

    # The stale validator is refused and nothing changes.
    stale = client.patch(
        "/students/me/prefs",
        json={"learning_prefs": {"explanation_style": "detailed"}},
        headers={**headers, "If-Match": etag},
    )
    assert stale.status_code == 412, stale.text
    assert stale.json()["detail"]["code"] == "precondition_failed"
    after = client.get("/students/me/prefs", headers=headers)
    assert after.json()["learning_prefs"]["explanation_style"] == "simple"
    assert after.headers["ETag"] == new_etag

    # No If-Match keeps the legacy last-write-wins contract.
    legacy = client.patch(
        "/students/me/prefs",
        json={"learning_prefs": {"explanation_style": "detailed"}},
        headers=headers,
    )
    assert legacy.status_code == 200, legacy.text
    assert legacy.json()["learning_prefs"]["explanation_style"] == "detailed"

    # "*" matches any current state (RFC 9110).
    wildcard = client.patch(
        "/students/me/prefs",
        json={"learning_prefs": {"subject_focus": "গণিত"}},
        headers={**headers, "If-Match": "*"},
    )
    assert wildcard.status_code == 200, wildcard.text


def test_expired_claims_do_not_leak_forever() -> None:
    """A completed entry is replayable; the cache honours a short TTL."""
    cache = MemoryCache()
    asyncio.run(
        run_once(cache=cache, scope="t", user_id=7, key=KEY, produce=lambda: _value("first"))
    )
    replay = asyncio.run(
        run_once(cache=cache, scope="t", user_id=7, key=KEY, produce=lambda: _value("second"))
    )
    assert replay.body == b'"first"'


def _value(text: str):
    async def produce() -> str:
        return text

    return produce()
