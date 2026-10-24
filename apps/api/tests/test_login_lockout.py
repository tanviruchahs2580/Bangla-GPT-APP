"""S-002: per-account failed-login lockout.

Before the fix the only anti-automation control on /auth/login was the per-IP
rule: with IP rotation any number of guesses against one known account was
possible. These tests pin the account-level behaviour:

* N failures lock the account and even the CORRECT password is refused while
  locked (429, stable code, Retry-After);
* the lock is progressive (the second lock is longer than the first);
* a successful sign-in resets the counter and clears the lock;
* an unknown email never creates a row and answers exactly like a wrong
  password.
"""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.models import User
from bangla_gpt_api.db.session import make_engine, make_session_factory
from bangla_gpt_api.main import create_app
from bangla_gpt_api.routers.auth import _LOGIN_LOCKOUT_THRESHOLD, LOGIN_LOCKED_CODE
from conftest import engine_url

PASSWORD = "supersecret1"
JWT = "test-secret-0123456789abcdef0123456789"
WRONG = "definitely-wrong"


def make_client(tmp_path, **overrides) -> tuple[TestClient, Settings]:
    settings = Settings(
        env="test",
        database_url=engine_url(tmp_path, "lockout"),
        jwt_secret=JWT,
        **overrides,
    )
    return TestClient(create_app(settings)), settings


def _register(client: TestClient, email: str) -> None:
    res = client.post(
        "/auth/register",
        json={
            "email": email,
            "password": PASSWORD,
            "name": "Tester",
            "role": "student",
            "guardian_consent": True,
            "class_level": 6,
        },
    )
    assert res.status_code == 201, res.text


def _login(client: TestClient, email: str, password: str):
    return client.post("/auth/login", json={"email": email, "password": password})


def _failed(client: TestClient, email: str, times: int) -> None:
    """Every failure must stay 401 until the counter crosses the threshold."""
    for i in range(times):
        res = _login(client, email, WRONG)
        assert res.status_code == 401, (i, res.text)
        assert res.json()["detail"]["code"] == "bad_credentials"


def _user_row(settings: Settings, email: str) -> User:
    with make_session_factory(make_engine(settings))() as db:
        user = db.execute(select(User).where(User.email == email)).scalar_one()
        db.expunge(user)
        return user


def _set_lock_in_the_past(settings: Settings, email: str) -> None:
    """Simulate the lock expiring without sleeping a minute."""
    with make_session_factory(make_engine(settings))() as db:
        user = db.execute(select(User).where(User.email == email)).scalar_one()
        user.locked_until = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
        db.commit()


def test_correct_password_is_refused_while_locked(tmp_path) -> None:
    client, settings = make_client(tmp_path)
    _register(client, "kid@example.test")
    _failed(client, "kid@example.test", _LOGIN_LOCKOUT_THRESHOLD)

    locked = _login(client, "kid@example.test", PASSWORD)
    assert locked.status_code == 429, locked.text
    assert locked.json()["detail"]["code"] == LOGIN_LOCKED_CODE
    retry_after = int(locked.headers["Retry-After"])
    assert retry_after >= 1

    # The wrong password is refused with the same coded 429 (not a 401 oracle
    # telling an attacker the lock is only against them).
    also_locked = _login(client, "kid@example.test", WRONG)
    assert also_locked.status_code == 429
    assert also_locked.json()["detail"]["code"] == LOGIN_LOCKED_CODE


def test_successful_login_after_expiry_resets_counter_and_lock(tmp_path) -> None:
    client, settings = make_client(tmp_path)
    _register(client, "kid@example.test")
    _failed(client, "kid@example.test", _LOGIN_LOCKOUT_THRESHOLD)
    assert _user_row(settings, "kid@example.test").failed_login_count >= _LOGIN_LOCKOUT_THRESHOLD
    assert _user_row(settings, "kid@example.test").locked_until is not None

    _set_lock_in_the_past(settings, "kid@example.test")
    ok = _login(client, "kid@example.test", PASSWORD)
    assert ok.status_code == 200, ok.text

    row = _user_row(settings, "kid@example.test")
    assert row.failed_login_count == 0
    assert row.locked_until is None

    # The next failure starts from one, proving the reset was persisted.
    assert _login(client, "kid@example.test", WRONG).status_code == 401
    assert _user_row(settings, "kid@example.test").failed_login_count == 1


def test_lock_is_progressive(tmp_path) -> None:
    client, settings = make_client(tmp_path)
    _register(client, "kid@example.test")
    _failed(client, "kid@example.test", _LOGIN_LOCKOUT_THRESHOLD)
    first = int(_login(client, "kid@example.test", PASSWORD).headers["Retry-After"])

    # Let the first lock lapse WITHOUT clearing the counter (that is what a
    # real expiry does), then fail once more: the counter is now above the
    # threshold and the new lock must be strictly longer.
    _set_lock_in_the_past(settings, "kid@example.test")
    assert _login(client, "kid@example.test", WRONG).status_code == 401
    second = int(_login(client, "kid@example.test", PASSWORD).headers["Retry-After"])
    assert second > first, (first, second)


def test_failures_below_threshold_do_not_lock(tmp_path) -> None:
    client, settings = make_client(tmp_path)
    _register(client, "kid@example.test")
    _failed(client, "kid@example.test", _LOGIN_LOCKOUT_THRESHOLD - 1)
    assert _user_row(settings, "kid@example.test").locked_until is None
    assert _login(client, "kid@example.test", PASSWORD).status_code == 200


def test_unknown_email_does_not_create_rows_or_leak(tmp_path) -> None:
    client, settings = make_client(tmp_path)
    _register(client, "known@example.test")
    unknown_before = _login(client, "ghost@example.test", WRONG)
    known_wrong = _login(client, "known@example.test", WRONG)

    # Identical status and body: the unknown address is indistinguishable from
    # a wrong password on a real account.
    assert unknown_before.status_code == known_wrong.status_code == 401
    assert unknown_before.json() == known_wrong.json()

    # Repeated unknown-address attempts create nothing and never lock.
    for _ in range(3):
        assert _login(client, "ghost@example.test", WRONG).status_code == 401
    with make_session_factory(make_engine(settings))() as db:
        ghosts = db.execute(
            select(func.count()).select_from(User).where(User.email == "ghost@example.test")
        ).scalar_one()
    assert ghosts == 0
    # And the real account was NOT touched by the unknown attempts: its single
    # failure is still below the threshold, so the correct password signs in.
    assert _login(client, "known@example.test", PASSWORD).status_code == 200


# --- the atomicity guarantee itself ------------------------------------------


def test_parallel_failures_each_count_exactly_once(tmp_path) -> None:
    """The lockout must arm under concurrent guessing, not just sequential.

    The original implementation was a read-modify-write on the ORM object:
    five parallel wrong-password requests all read the counter before any of
    them committed (Argon2id verification takes tens of milliseconds, so the
    reads genuinely overlap), all wrote the same value, and the lock never
    armed. Five sockets defeated the account-level control this whole module
    documents. The counter is now incremented by a single database-side
    UPDATE, so the invariant asserted here — *the stored counter equals the
    number of counted failures* — holds under any interleaving.

    Every response is a 401 (counted) or a 429 (already-locked, not
    counted); a thread that starts after the lock armed legitimately sees
    429 and does not increment. The equalities below pin exactly that.
    """
    import threading

    client, settings = make_client(tmp_path)
    _register(client, "burst@example.test")

    attempts = _LOGIN_LOCKOUT_THRESHOLD
    barrier = threading.Barrier(attempts)
    statuses: list[int] = []
    statuses_lock = threading.Lock()

    def attempt() -> None:
        barrier.wait(5)
        res = _login(client, "burst@example.test", WRONG)
        with statuses_lock:
            statuses.append(res.status_code)

    threads = [threading.Thread(target=attempt) for _ in range(attempts)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)

    assert len(statuses) == attempts
    counted_failures = statuses.count(401)
    already_locked = statuses.count(429)
    assert counted_failures + already_locked == attempts, statuses

    row = _user_row(settings, "burst@example.test")
    # The lost-update detector: the counter must equal the failures that were
    # actually answered with "wrong password", never fewer.
    assert row.failed_login_count == counted_failures, (
        f"{counted_failures} wrong-password 401s but the counter holds "
        f"{row.failed_login_count} — increments were lost to a race"
    )
    # And the account is locked: either the failures crossed the threshold or
    # a 429 proved it was already crossed.
    assert row.locked_until is not None
    assert _login(client, "burst@example.test", PASSWORD).status_code == 429
