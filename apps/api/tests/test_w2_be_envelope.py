"""W2/BE: the coded error envelope holds on every path (F-067, F-074).

The audit found the last three list/string-shaped ``HTTPException`` details in
``routers/`` (all in ``teacher_content.py``) and an auth guard answering
``{"detail": "<string>"}``, which a client cannot classify by ``detail.code``.
The AST test below makes the shape a property of the whole ``routers/`` tree
rather than a spot check: FastAPI cannot see helper-raised exceptions, so a
static scan is the only guard that reaches them.
"""

import ast
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app
from bangla_gpt_api.routers._error_contract import AUTH_CODES

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"

ROUTERS_DIR = Path(__file__).resolve().parents[1] / "src" / "bangla_gpt_api" / "routers"


def _http_exception_calls(tree: ast.AST) -> list[ast.Call]:
    calls = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "HTTPException"
        ):
            calls.append(node)
    return calls


def test_every_http_exception_detail_is_dict_shaped() -> None:
    """Every raise in routers/ passes a dict (or a dict-shaped expression).

    ``detail=<str>`` and ``detail=[...]`` are what the 2026-10-29 audit found
    on three teacher-generator sites; the client's error map branches on
    ``detail.code``, so a non-dict detail silently defeats it.
    """
    offenders: list[str] = []
    scanned = 0
    for path in sorted(ROUTERS_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for call in _http_exception_calls(tree):
            scanned += 1
            detail = next((kw.value for kw in call.keywords if kw.arg == "detail"), None)
            if detail is None:
                offenders.append(f"{path.name}:{call.lineno} raises without a detail")
                continue
            if isinstance(detail, (ast.Dict, ast.Call)):
                continue
            if isinstance(detail, ast.List) and all(isinstance(e, ast.Dict) for e in detail.elts):
                offenders.append(f"{path.name}:{call.lineno} returns a list of dicts")
                continue
            offenders.append(
                f"{path.name}:{call.lineno} detail is {type(detail).__name__}, not a dict"
            )
    assert scanned > 50, f"scan found only {scanned} HTTPException raises; regex/scope broke"
    assert not offenders, "non-coded error details: " + "; ".join(offenders)


@pytest.fixture
def client(tmp_path) -> TestClient:
    settings = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path}/envelope.db",
        jwt_secret=SECRET,
    )
    return TestClient(create_app(settings))


def _register(client: TestClient, email: str, role: str = "teacher") -> None:
    payload: dict = {"email": email, "password": PASSWORD, "name": "Tutor", "role": role}
    if role == "student":
        payload["guardian_consent"] = True
        payload["class_level"] = 6
    assert client.post("/auth/register", json=payload).status_code == 201


def _headers(client: TestClient, email: str) -> dict:
    res = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def test_missing_token_is_a_coded_401(client: TestClient) -> None:
    res = client.get("/learn/subjects")
    assert res.status_code == 401
    assert res.json()["detail"] == {"code": "unauthenticated", "message": "Not authenticated"}


def test_invalid_token_is_a_coded_401(client: TestClient) -> None:
    res = client.get("/learn/subjects", headers={"Authorization": "Bearer not-a-token"})
    assert res.status_code == 401
    assert res.json()["detail"]["code"] == "invalid_token"


def test_insufficient_role_is_a_coded_403(client: TestClient) -> None:
    client.post(
        "/auth/register",
        json={
            "email": "nobody@example.com",
            "password": PASSWORD,
            "name": "Nobody",
            "role": "student",
            "guardian_consent": True,
            "class_level": 6,
        },
    )
    headers = _headers(client, "nobody@example.com")
    res = client.get("/admin/users", headers=headers)
    assert res.status_code == 403
    assert res.json()["detail"]["code"] == "insufficient_role"


def test_every_401_code_used_by_deps_is_declared() -> None:
    """The stable code list in _error_contract must cover every site."""
    source = (ROUTERS_DIR / "deps.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    used = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_unauthorized"
        ):
            code = next((kw.value for kw in node.keywords if kw.arg == "code"), None)
            if isinstance(code, ast.Constant):
                used.add(code.value)
    assert used, "no coded 401 sites found; the AST scan broke"
    assert used <= set(AUTH_CODES[401]), sorted(used - set(AUTH_CODES[401]))


def test_unknown_generator_kind_is_a_coded_404(client: TestClient) -> None:
    _register(client, "kind@example.com")
    headers = _headers(client, "kind@example.com")
    res = client.post(
        "/teacher/generate/bogus", json={"subject": "x", "class_level": 6}, headers=headers
    )
    assert res.status_code == 404
    assert res.json()["detail"] == {"code": "unknown_kind", "message": "unknown generator kind"}


def test_malformed_generator_payload_is_a_coded_422(client: TestClient) -> None:
    _register(client, "malformed@example.com")
    headers = _headers(client, "malformed@example.com")
    res = client.post("/teacher/generate/worksheet", json={"subject": "science"}, headers=headers)
    assert res.status_code == 422
    assert res.json()["detail"] == {
        "code": "invalid_payload",
        "message": "invalid worksheet payload",
    }


def test_answer_key_with_unknown_paper_is_a_coded_404(client: TestClient) -> None:
    _register(client, "paper@example.com")
    headers = _headers(client, "paper@example.com")
    res = client.post(
        "/teacher/generate/answer_key",
        json={"subject": "science", "class_level": 6, "paper_id": 999_999},
        headers=headers,
    )
    assert res.status_code == 404
    assert res.json()["detail"] == {"code": "not_found", "message": "question paper not found"}


def test_answer_key_without_a_source_is_a_coded_422(client: TestClient) -> None:
    """The schema refuses a key with neither paper_id nor questions; the
    answer is the coded envelope, not pydantic's internal error list."""
    _register(client, "emptykey@example.com")
    headers = _headers(client, "emptykey@example.com")
    res = client.post(
        "/teacher/generate/answer_key",
        json={"subject": "science", "class_level": 6},
        headers=headers,
    )
    assert res.status_code == 422
    assert res.json()["detail"] == {
        "code": "invalid_payload",
        "message": "invalid answer_key payload",
    }


def test_doc_in_for_unknown_kind_carries_its_coded_status() -> None:
    """The AiJob runner path (workspace.py) shares _doc_in_for; its failure
    must be the same coded status the sync route returns, not a bare
    LookupError whose text lands in a job record."""
    from bangla_gpt_api.routers.common import DocumentInputError, _doc_in_for

    with pytest.raises(DocumentInputError) as caught:
        _doc_in_for("bogus", {})
    assert (caught.value.status_code, caught.value.code) == (404, "unknown_kind")
    assert str(caught.value) == "unknown generator kind"
