"""A10-03 (board serialises the version payload) + A1-04 (kg/rebuild ledger).

Two admin-endpoint closures, each pinned at the HTTP seam:

* A10-03 — the AI-quality board must surface WHICH prompt registry, index
  fingerprint and embedding model produced the counts it shows. The payload
  builder (``evaluation/version_board.py``) existed since r3; this pins that
  the endpoint actually serialises it.
* A1-04 — ``POST /kg/rebuild?llm=true`` runs real LLM extraction calls and
  must land them in the same ai_usage ledger every other AI route writes
  (the last un-accounted provider call site; acknowledged in-code before the
  fix).
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from bangla_gpt_api.config import Settings
from bangla_gpt_api.db.models import AiUsage
from bangla_gpt_api.db.session import make_engine, make_session_factory
from bangla_gpt_api.main import create_app

SECRET = "test-secret-0123456789abcdef0123456789"
PASSWORD = "StrongPass123!"


def _settings(tmp_path, **over) -> Settings:
    base = dict(env="test", database_url=f"sqlite:///{tmp_path}/board.db", jwt_secret=SECRET)
    base.update(over)
    return Settings(**base)


def _admin_headers(client: TestClient) -> dict[str, str]:
    root = client.post("/auth/login", json={"email": "root@example.com", "password": PASSWORD})
    assert root.status_code == 200, root.text
    return {"Authorization": f"Bearer {root.json()['access_token']}"}


def _admin_client(tmp_path) -> TestClient:
    return TestClient(
        create_app(
            _settings(
                tmp_path,
                admin_email="root@example.com",
                admin_password=PASSWORD,
                force_admin_password_change=False,
            )
        )
    )


def test_ai_quality_board_serialises_the_version_payload(tmp_path) -> None:
    """A10-03: versions are visible ON the endpoint, not only via the CLI."""
    client = _admin_client(tmp_path)
    admin = _admin_headers(client)
    res = client.get("/admin/ai/quality", headers=admin)
    assert res.status_code == 200, res.text
    versions = res.json()["versions"]

    # Prompt registry: the identity of EVERY prompt the app sends.
    registry = versions["prompt_registry"]
    assert registry["manifest"] == "manifest.json"
    assert registry["prompt_count"] > 0
    assert any(p["id"] == "tutor_system" for p in registry["prompts"])
    assert versions["prompt"]["tutor_system"].startswith("tutor_system@")

    # Index + embedding: the running identities (mock index in tests, but the
    # tutor's corpus fingerprint rides through when a tutor is built).
    tutor_fingerprint = versions["index"]["fingerprint"]
    assert tutor_fingerprint is None or isinstance(tutor_fingerprint, str)
    assert versions["embedding"]["model"] == client.app.state.ctx.settings.embedding_model

    # Evaluation identities come from the tracked artifacts.
    assert versions["evaluation"]["thresholds_version"] >= 1
    assert versions["evaluation"]["golden"]["file"] == "golden_v2.json"


def test_kg_rebuild_llm_extraction_lands_in_the_usage_ledger(tmp_path) -> None:
    """A1-04: the last un-accounted AI call site writes its token rows.

    The mock provider's answer never parses into concept names, but the
    generate() call still happened per chapter — spend is spend, so the
    ledger must show it with route ``tutor-style`` identity.
    """
    app = create_app(
        _settings(
            tmp_path,
            admin_email="root@example.com",
            admin_password=PASSWORD,
            force_admin_password_change=False,
        )
    )
    client = TestClient(app)
    admin = _admin_headers(client)

    res = client.post("/kg/rebuild", headers=admin)
    assert res.status_code == 200, res.text
    assert res.json()["llm_concepts"] == 0

    engine = make_engine(_settings(tmp_path))

    def ledger_count(route: str | None) -> int:
        factory = make_session_factory(engine)
        with factory() as db:
            stmt = select(func.count()).select_from(AiUsage)
            if route is not None:
                stmt = stmt.where(AiUsage.route == route)
            return int(db.execute(stmt).scalar_one())

    assert ledger_count(None) == 0, "the deterministic rebuild spends no tokens"

    res_llm = client.post("/kg/rebuild?llm=true", headers=admin)
    assert res_llm.status_code == 200, res_llm.text
    # The mock extraction ran (zero parseable names is its honest result) and
    # every generate() call it made is now in the ledger.
    assert ledger_count(None) > 0, "kg/rebuild?llm=true must account its provider calls"
    rows_llm = ledger_count("kg.rebuild") + ledger_count("kg/rebuild")
    assert rows_llm == ledger_count(None), "the extraction rows carry the kg route label"
