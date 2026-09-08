"""S1.5 — 'আমি বুঝিনি' adaptive re-teach: strategy cycle + injection."""

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app
from bangla_gpt_api.services.teach_strategy import (
    STRATEGIES,
    next_strategy,
    reteach_instruction,
    strategy_name,
)


@pytest.fixture
def client(tmp_path) -> TestClient:
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/reteach.db",
        jwt_secret="test-secret-0123456789abcdef0123456789",
    )
    return TestClient(create_app(settings))


@pytest.fixture
def student(client: TestClient) -> dict[str, str]:
    client.post(
        "/auth/register",
        json={
            "email": "rt@example.com",
            "password": "supersecret1",
            "name": "শিক্ষার্থী",
            "role": "student",
            "guardian_consent": True,
            "class_level": 6,
        },
    )
    login = client.post("/auth/login", json={"email": "rt@example.com", "password": "supersecret1"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_next_strategy_cycles_through_all_strategies() -> None:
    keys = [k for k, _ in STRATEGIES]
    seen: list[str] = []
    last: str | None = None
    for _ in keys:
        last = next_strategy(last)
        seen.append(last)
    assert seen == keys  # full cycle, each exactly once
    assert next_strategy(last) == keys[0]  # wraps around
    assert next_strategy("bogus") == keys[0]


def test_same_failure_injects_a_different_strategy() -> None:
    """Spec PASS: same question twice ⇒ a different strategy is injected."""
    failed = "simple"
    key1, instr1 = reteach_instruction(failed)
    key2, instr2 = reteach_instruction(key1)
    assert key1 != failed and key2 != key1
    # The failed approach is named as failed; the new approach is named as the
    # one to use — and the two instructions differ.
    assert strategy_name(failed) in instr1 and strategy_name(key1) in instr1
    assert strategy_name(key1) in instr2 and strategy_name(key2) in instr2
    assert instr1 != instr2


def test_reteach_turn_persists_and_rotates_strategy(client: TestClient, student: dict) -> None:
    """Two reteach turns on the same question store different strategies."""
    conv = client.post("/tutor/conversations", json={}, headers=student).json()
    question = "কোষের প্রধান অংশ কী কী?"
    # Plain turn: no strategy chosen.
    client.post(
        f"/tutor/conversations/{conv['id']}/messages",
        json={"message": question, "class_level": 6, "subject": "science"},
        headers=student,
    )
    conversations = client.get("/tutor/conversations", headers=student).json()
    assert next(c for c in conversations if c["id"] == conv["id"])["last_strategy"] is None

    first = client.post(
        f"/tutor/conversations/{conv['id']}/messages",
        json={"message": question, "class_level": 6, "subject": "science", "reteach": True},
        headers=student,
    ).json()
    assert first["grounded"] is True
    strategies = [next_strategy(None)]

    second = client.post(
        f"/tutor/conversations/{conv['id']}/messages",
        json={"message": question, "class_level": 6, "subject": "science", "reteach": True},
        headers=student,
    ).json()
    assert second["grounded"] is True
    strategies.append(next_strategy(strategies[-1]))

    conversations = client.get("/tutor/conversations", headers=student).json()
    after = next(c for c in conversations if c["id"] == conv["id"])["last_strategy"]
    assert after == strategies[-1]
    assert len(set(strategies)) == 2, "reteach must rotate to a different strategy"
