"""F-082 / DATA-06: the served corpus identity is exposed and stamped.

The boot log alone could not answer "which corpus build produced this
answer". The identity (kind, chunk count, artifact digest, manifest hash) is
now served by /admin/system/info and stamped on every citation and per-answer
trace, so an answer and the build behind it can be joined in one hop.
"""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app
from conftest import engine_url

PASSWORD = "supersecret1"
SECRET = "test-secret-0123456789abcdef0123456789"
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


def _app(tmp_path, name: str) -> TestClient:
    settings = Settings(
        env="test",
        database_url=engine_url(tmp_path, name),
        jwt_secret=SECRET,
        admin_email="adm@test.com",
        admin_password=PASSWORD,
        force_admin_password_change=False,
    )
    return create_app(settings)


def _admin_headers(client: TestClient) -> dict[str, str]:
    res = client.post("/auth/login", json={"email": "adm@test.com", "password": PASSWORD})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _student_headers(client: TestClient) -> dict[str, str]:
    res = client.post(
        "/auth/register",
        json={
            "email": "student@example.com",
            "password": PASSWORD,
            "name": "শিক্ষার্থী",
            "role": "student",
            "class_level": 6,
            "guardian_consent": True,
        },
    )
    assert res.status_code == 201, res.text
    login = client.post("/auth/login", json={"email": "student@example.com", "password": PASSWORD})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_admin_system_info_exposes_the_served_corpus_identity(tmp_path) -> None:
    app = _app(tmp_path, "w2xcorpus")
    client = TestClient(app)
    res = client.get("/admin/system/info", headers=_admin_headers(client))
    assert res.status_code == 200, res.text
    corpus = res.json()["corpus"]
    assert corpus == app.state.ctx.corpus_identity
    assert corpus["kind"] in ("nctb", "bundled-sample")
    assert corpus["chunks"] > 0
    assert _DIGEST_RE.match(corpus["digest"])


def test_the_identity_is_deterministic_across_boots(tmp_path) -> None:
    first = _app(tmp_path, "w2xcorpus-a")
    second = _app(tmp_path, "w2xcorpus-b")
    assert first.state.ctx.corpus_identity == second.state.ctx.corpus_identity


def test_answer_citations_and_trace_carry_the_corpus_digest(tmp_path) -> None:
    app = _app(tmp_path, "w2xcorpus-answer")
    client = TestClient(app)
    digest = app.state.ctx.corpus_identity["digest"]
    res = client.post(
        "/tutor/ask",
        json={"question": "কোষ কী?", "class_level": 6, "subject": "science"},
        headers=_student_headers(client),
    )
    assert res.status_code == 200, res.text
    sources = res.json()["sources"]
    assert sources, "a grounded answer must cite sources"
    assert all(source["corpus_version"] == digest for source in sources)
    traces = app.state.ctx.tutor.trace_store.recent(1)
    assert traces[0].parameters["corpus_digest"] == digest
