"""API-01/API-02: the served OpenAPI document must match runtime behaviour.

AUD-0052 recorded three contract drifts; AUD-0053 six endpoints that rejected
schema-valid input; AUD-0055 199 undocumented status codes. These tests pin
the contract so it cannot silently drift again:

* every documented error status is documented with a real body model;
* the operations that used to reject schema-valid requests now answer with a
  documented status;
* POST /feedback advertises its success body instead of an open ``dict``;
* note ``source_ref`` is a bounded, typed object rather than any JSON.
"""

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app
from conftest import engine_url

PASSWORD = "supersecret1"


@pytest.fixture
def client(tmp_path):
    settings = Settings(
        env="test",
        database_url=engine_url(tmp_path, "contract"),
        jwt_secret="test-secret-0123456789abcdef0123456789",
        admin_email="root@example.com",
        admin_password=PASSWORD,
        force_admin_password_change=False,
    )
    with TestClient(create_app(settings)) as c:
        yield c


def _schema(client: TestClient) -> dict:
    return client.get("/openapi.json").json()


def _op(schema: dict, method: str, path: str) -> dict:
    return schema["paths"][path][method]


def test_auth_guard_errors_are_documented_on_every_protected_operation(client):
    """AUD-0055: the 188 undocumented 401s came from auth dependencies that
    FastAPI cannot see. They are now declared once per router."""
    schema = _schema(client)
    unauthenticated = {
        ("get", "/tutor/conversations"),
        ("get", "/teacher/classrooms"),
        ("get", "/school/overview"),
        ("get", "/notes"),
        ("get", "/users/me"),
        ("get", "/admin/users"),
        ("get", "/parents/me/children"),
        ("post", "/students/me/invite-code"),
        ("get", "/learn/subjects"),
    }
    for method, path in unauthenticated:
        responses = _op(schema, method, path)["responses"]
        assert "401" in responses, f"{method.upper()} {path} does not document 401"
        assert responses["401"]["content"]["application/json"]["schema"]["$ref"].endswith(
            "MessageDetail"
        )


def test_register_documents_its_business_conflicts(client):
    """AUD-0053: student registration rejections are a documented 409."""
    responses = _op(_schema(client), "post", "/auth/register")["responses"]
    assert "409" in responses
    assert responses["409"]["content"]["application/json"]["schema"]["$ref"].endswith("CodedDetail")


def test_register_rejects_schema_valid_student_with_documented_status(client):
    # schema-valid but business-invalid: role=student with no consent/class_level
    res = client.post(
        "/auth/register",
        json={
            "email": "s@student.test",
            "password": PASSWORD,
            "name": "Student",
            "role": "student",
            "guardian_consent": False,
        },
    )
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "class_level_required"

    res = client.post(
        "/auth/register",
        json={
            "email": "s@student.test",
            "password": PASSWORD,
            "name": "Student",
            "role": "student",
            "class_level": 6,
            "guardian_consent": False,
        },
    )
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "guardian_consent_required"


def test_feedback_success_body_is_advertised_and_enforced(client):
    """AUD-0052: the handler returned an untyped dict."""
    op = _op(_schema(client), "post", "/feedback")
    assert op["responses"]["201"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "FeedbackOut"
    )
    assert "400" in op["responses"]
    assert op["responses"]["400"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "CodedDetail"
    )


def test_feedback_without_target_is_400_not_422(client):
    """AUD-0053: `{"rating": 0}` is schema-valid; the old handler answered 422,
    whose documented body is FastAPI's validation-error array."""
    headers = {"Authorization": "Bearer " + _token(client)}
    res = client.post("/feedback", json={"rating": 0}, headers=headers)
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "missing_target"


def test_change_password_documents_its_rejections(client):
    responses = _op(_schema(client), "post", "/auth/change-password")["responses"]
    assert "400" in responses and "409" in responses


def test_parent_link_invite_documents_400_and_409(client):
    responses = _op(_schema(client), "post", "/parents/link/invite")["responses"]
    assert responses["400"]["content"]["application/json"]["schema"]["$ref"].endswith("CodedDetail")
    assert responses["409"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "MessageDetail"
    )


def test_consent_reconfirm_documents_its_rejections(client):
    responses = _op(_schema(client), "post", "/students/{student_id}/consent/reconfirm")[
        "responses"
    ]
    assert "400" in responses and "403" in responses and "404" in responses


def test_note_source_ref_is_bounded_not_arbitrary_json(client):
    """AUD-0052: `dict[str, Any]` let a client persist unbounded JSON."""
    ref_schema = _schema(client)["components"]["schemas"]["NoteSourceRef-Input"]
    assert ref_schema.get("additionalProperties") is False
    assert set(ref_schema["properties"]) == {"subject", "chapter", "class_level", "message_id"}

    headers = {"Authorization": "Bearer " + _token(client)}
    rejected = client.post(
        "/notes",
        json={"body": "x", "source_ref": {"anything": "goes", "nested": {"a": [1, 2]}}},
        headers=headers,
    )
    assert rejected.status_code == 422

    accepted = client.post(
        "/notes",
        json={"body": "x", "source_ref": {"chapter": "kosh", "class_level": 6}},
        headers=headers,
    )
    assert accepted.status_code == 201
    assert accepted.json()["source_ref"] == {"chapter": "kosh", "class_level": 6}


def _token(client: TestClient) -> str:
    res = client.post("/auth/login", json={"email": "root@example.com", "password": PASSWORD})
    assert res.status_code == 200, res.text
    return res.json()["access_token"]
