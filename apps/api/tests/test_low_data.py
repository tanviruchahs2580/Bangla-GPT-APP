"""S1.13: low-data mode asks the tutor for a measurably shorter payload."""

import json

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app

KOSH = chr(0x0995) + chr(0x09CB) + chr(0x09B7)  # "koshe ki" style cell question word


@pytest.fixture
def client(tmp_path) -> TestClient:
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/lowdata.db",
        jwt_secret="test-secret-0123456789abcdef0123456789",
    )
    return TestClient(create_app(settings))


def _auth(client: TestClient) -> dict[str, str]:
    reg = client.post(
        "/auth/register",
        json={
            "email": "lowdata@example.com",
            "password": "supersecret1",
            "name": "LD Kid",
            "role": "student",
            "guardian_consent": True,
            "class_level": 6,
        },
    )
    assert reg.status_code == 201, reg.text
    login = client.post(
        "/auth/login", json={"email": "lowdata@example.com", "password": "supersecret1"}
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _ask(client: TestClient, question: str, low_data: bool, headers: dict[str, str]) -> dict:
    resp = client.post(
        "/tutor/ask",
        json={"question": question, "class_level": 6, "subject": "science", "low_data": low_data},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_low_data_answer_is_shorter(client: TestClient) -> None:
    question = KOSH + " " + chr(0x0995) + chr(0x09C0)  # "kosha ki"
    headers = _auth(client)
    full = _ask(client, question, low_data=False, headers=headers)
    short = _ask(client, question, low_data=True, headers=headers)
    assert full["grounded"] and short["grounded"]
    assert len(short["answer"]) < len(full["answer"])
    # payload size reduction is measurable end-to-end, not just in prose
    assert len(json.dumps(short, ensure_ascii=False)) < len(json.dumps(full, ensure_ascii=False))


def test_low_data_keeps_only_the_simple_section(client: TestClient) -> None:
    from bangla_gpt_api.services.answer_structure import SECTION_POINTS, SECTION_SIMPLE

    question = KOSH + " " + chr(0x0995) + chr(0x09C0)
    headers = _auth(client)
    short = _ask(client, question, low_data=True, headers=headers)
    full = _ask(client, question, low_data=False, headers=headers)
    assert SECTION_SIMPLE in short["answer"]
    assert SECTION_POINTS in full["answer"]
    assert SECTION_POINTS not in short["answer"]


def test_low_data_defaults_to_off(client: TestClient) -> None:
    question = KOSH + " " + chr(0x0995) + chr(0x09C0)
    resp = client.post(
        "/tutor/ask",
        json={"question": question, "class_level": 6, "subject": "science"},
        headers=_auth(client),
    )
    assert resp.status_code == 200
    from bangla_gpt_api.services.answer_structure import SECTION_POINTS

    assert SECTION_POINTS in resp.json()["answer"]
