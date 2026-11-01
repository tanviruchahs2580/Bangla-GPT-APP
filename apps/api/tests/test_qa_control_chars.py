"""F-005 / API-04: identity fields reject control and bidi-formatting characters.

The probe behind the finding registered ``evil\\u0000name`` and ``abc\\u202edef``
and both answered 201 with the characters stored verbatim. SQLite tolerated the
NUL; PostgreSQL cannot store code zero at all, so the identical request is a 500
on the production engine, and U+202E lets a roster/report/PDF entry render as a
different string. These tests pin the 422 with the stable ``invalid_characters``
error type on every identity/profile schema, and pin the deliberate exemption:
free-text bodies keep the characters.
"""

from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select

from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.models import Student, User
from bangla_gpt_api.db.session import make_engine, make_session_factory
from bangla_gpt_api.main import create_app
from bangla_gpt_api.schemas import (
    ChatSendRequest,
    SavedNoteIn,
    SchoolCreateIn,
    SchoolJoinIn,
)
from conftest import engine_url

PASSWORD = "supersecret1"
JWT = "test-secret-0123456789abcdef0123456789"
NUL = "\u0000"
RLO = "\u202e"  # right-to-left override
LRI = "\u2066"  # left-to-right isolate


def _client(tmp_path) -> TestClient:
    settings = Settings(
        env="test",
        database_url=engine_url(tmp_path, "control-chars"),
        jwt_secret=JWT,
    )
    return TestClient(create_app(settings))


def _register_body(**overrides) -> dict:
    body = {
        "email": "kid@example.test",
        "password": PASSWORD,
        "name": "Kid",
        "role": "student",
        "guardian_consent": True,
        "class_level": 6,
    }
    body.update(overrides)
    return body


def _invalid_characters_codes(response) -> list[str]:
    return [err.get("type", "") for err in response.json()["detail"]]


def test_register_rejects_nul_and_bidi_names(tmp_path) -> None:
    client = _client(tmp_path)
    for bad_name in (f"evil{NUL}name", f"abc{RLO}def", f"{LRI}x\u2069"):
        res = client.post("/auth/register", json=_register_body(name=bad_name))
        assert res.status_code == 422, (bad_name, res.text)
        assert "invalid_characters" in _invalid_characters_codes(res), res.text


def test_register_rejects_control_characters_in_identity_fields(tmp_path) -> None:
    client = _client(tmp_path)
    # email: the permissive `[^@\s]` pattern alone would have accepted the NUL.
    res = client.post("/auth/register", json=_register_body(email=f"kid{NUL}@example.test"))
    assert res.status_code == 422, res.text
    assert "invalid_characters" in _invalid_characters_codes(res)
    # phone (parent role): stored encrypted, but the raw value still reaches
    # the Fernet write and the error log.
    res = client.post(
        "/auth/register",
        json=_register_body(
            role="parent", class_level=None, guardian_consent=False, phone=f"017{RLO}1234"
        ),
    )
    assert res.status_code == 422, res.text
    assert "invalid_characters" in _invalid_characters_codes(res)


def test_rejected_registration_writes_no_rows(tmp_path) -> None:
    client = _client(tmp_path)
    res = client.post("/auth/register", json=_register_body(name=f"evil{NUL}name"))
    assert res.status_code == 422
    settings = Settings(database_url=engine_url(tmp_path, "control-chars"), jwt_secret=JWT)
    with make_session_factory(make_engine(settings))() as db:
        assert db.execute(select(func.count()).select_from(User)).scalar_one() == 0
        assert db.execute(select(func.count()).select_from(Student)).scalar_one() == 0


def test_school_and_login_identity_fields_share_the_validator() -> None:
    for model, kwargs in (
        (SchoolCreateIn, {"name": f"School{NUL}One"}),
        (
            SchoolJoinIn,
            {
                "invite_code": "ABCD1234",
                "email": "a@b.example",
                "password": "longenough1",
                "name": f"x{RLO}y",
            },
        ),
    ):
        try:
            model(**kwargs)
        except ValidationError as exc:
            assert [e["type"] for e in exc.errors()] == ["invalid_characters"], exc.errors()
        else:  # pragma: no cover - the assertion below is the real check
            raise AssertionError(f"{model.__name__} accepted a control character")


def test_free_text_bodies_keep_bidi_characters() -> None:
    """Documented exemption: prose is allowed bidirectional text."""
    assert ChatSendRequest(message=f"why does {RLO}this happen?", class_level=6).message
    assert SavedNoteIn(body=f"note {LRI}with isolate\u2069").body


def test_other_control_codes_stay_allowed_in_names() -> None:
    """Boundary of the block list: PostgreSQL stores these and legacy rows carry them.

    The guard rejects exactly U+0000 and the bidi formatting set; a blanket
    control-character ban would start refusing mis-encoded legacy names that
    the existing suite registers (tests/test_auth_teacher.py).
    """
    from bangla_gpt_api.schemas import RegisterRequest

    accepted = RegisterRequest(
        email="kid@example.test",
        password="supersecret1",
        name="Kid\u008dName",  # C1 char from a legacy mis-encoding
        role="student",
        class_level=6,
        guardian_consent=True,
    )
    assert "\u008d" in accepted.name
