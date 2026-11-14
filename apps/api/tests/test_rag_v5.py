"""RAG V5 — neural adapter, verification modes, and boot guards.

Covers the Master Prompt's W2/W7 minimal vertical slice:

* NeuralEmbedder identity (name binds model@revision), E5 query/document
  prefixes, dimension/finite-value validation, batching — all against an
  injected fake backend (no network, no model download).
* get_embedder: the neural lane is an explicit selection; missing
  model/dimension refuse loudly; the default stays HashingEmbedder.
* Evidence verification modes: off (payload byte-identical to pre-V5),
  shadow (additive verification_status from the deterministic citation
  verdict, never blocking), enforce (boot-guarded behind an explicit
  approval flag — no calibrated verifier exists).
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app
from bangla_gpt_api.retrieval.embedding import (
    HashingEmbedder,
    build_embedder,
)
from bangla_gpt_api.retrieval.neural_embedder import NeuralEmbedder
from conftest import engine_url

SECRET = "x" * 48
PASSWORD = "Str0ngPassphrase!42"


class FakeE5Backend:
    """Deterministic stand-in for sentence-transformers.encode."""

    def __init__(self, dim: int = 384) -> None:
        self.dim = dim
        self.seen: list[list[str]] = []

    def encode(self, sentences: list[str], **kwargs: Any) -> list[list[float]]:
        self.seen.append(list(sentences))
        out = []
        for s in sentences:
            vec = [0.0] * self.dim
            for i, ch in enumerate(s[: self.dim]):
                vec[i % self.dim] += (ord(ch) % 97) / 97.0
            out.append(vec)
        return out


# ---------- neural adapter (W2) ----------


def test_neural_embedder_identity_and_prefixes() -> None:
    backend = FakeE5Backend()
    emb = NeuralEmbedder(
        model_id="intfloat/multilingual-e5-small",
        dim=384,
        revision="v1",
        backend=backend,
    )
    assert emb.name == "neural:intfloat/multilingual-e5-small@v1"
    docs = emb.embed(["কোষ হলো গঠনগত একক"])
    queries = emb.embed_query(["কোষ কী?"])
    assert len(docs) == 1 and len(queries) == 1
    assert len(docs[0]) == 384 and len(queries[0]) == 384
    # E5 asymmetric prefixes are part of the recorded identity
    assert backend.seen[0][0].startswith("passage: ")
    assert backend.seen[1][0].startswith("query: ")
    # L2-normalised
    norm = sum(v * v for v in docs[0]) ** 0.5
    assert abs(norm - 1.0) < 1e-6


def test_neural_embedder_rejects_wrong_dim_and_nonfinite() -> None:
    class WrongDim(FakeE5Backend):
        def encode(self, sentences: list[str], **kwargs: Any) -> list[list[float]]:
            return [[0.1] * 10 for _ in sentences]

    with pytest.raises(ValueError, match="dim"):
        NeuralEmbedder(model_id="m", dim=384, backend=WrongDim()).embed(["x"])

    class NonFinite(FakeE5Backend):
        def encode(self, sentences: list[str], **kwargs: Any) -> list[list[float]]:
            return [[float("nan")] * 384 for _ in sentences]

    with pytest.raises(ValueError, match="non-finite"):
        NeuralEmbedder(model_id="m", dim=384, backend=NonFinite()).embed(["x"])


def test_neural_embedder_batches_and_handles_empty() -> None:
    backend = FakeE5Backend()
    emb = NeuralEmbedder(model_id="m", dim=384, backend=backend, batch_size=2)
    assert emb.embed([]) == []
    out = emb.embed(["a", "b", "c", "d", "e"])
    assert len(out) == 5
    assert len(backend.seen) == 3  # 2 + 2 + 1


def test_get_embedder_default_is_hashing_and_neural_is_explicit(tmp_path) -> None:
    settings = Settings(
        env="test",
        database_url=engine_url(tmp_path, "embdef"),
        jwt_secret=SECRET,
    )
    assert isinstance(build_embedder(settings), HashingEmbedder)

    neural_settings = Settings(
        env="test",
        database_url=engine_url(tmp_path, "embneural"),
        jwt_secret=SECRET,
        embedding_provider="neural",
        embedding_model="intfloat/multilingual-e5-small",
        embedding_model_revision="v1",
        embedding_dimension=384,
    )
    # the real backend needs the sentence-transformers dependency; without
    # it the lane refuses loudly (never a silent downgrade to hashing)
    try:
        import sentence_transformers  # noqa: F401

        emb = build_embedder(neural_settings)
        assert isinstance(emb, NeuralEmbedder)
        assert "multilingual-e5-small" in emb.name
    except ModuleNotFoundError:
        from bangla_gpt_api.retrieval.neural_embedder import (
            ProviderNotInstalledNeural,
        )

        with pytest.raises(ProviderNotInstalledNeural):
            build_embedder(neural_settings)

    # missing dimension refuses loudly (identity is a gate, not a guess)
    bad = Settings(
        env="test",
        database_url=engine_url(tmp_path, "embbad"),
        jwt_secret=SECRET,
        embedding_provider="neural",
        embedding_model="intfloat/multilingual-e5-small",
    )
    with pytest.raises(Exception, match="EMBEDDING_DIMENSION"):
        build_embedder(bad)


# ---------- verification modes (W7) ----------


def _register_ask(client: TestClient, question: str) -> dict:
    reg = client.post(
        "/auth/register",
        json={
            "email": "v5@example.com",
            "password": PASSWORD,
            "name": "V5",
            "role": "student",
            "class_level": 6,
            "guardian_consent": True,
        },
    )
    assert reg.status_code == 201, reg.text
    login = client.post("/auth/login", json={"email": "v5@example.com", "password": PASSWORD})
    assert login.status_code == 200
    client.headers.update({"Authorization": f"Bearer {login.json()['access_token']}"})
    res = client.post("/tutor/ask", json={"question": question, "class_level": 6})
    assert res.status_code == 200, res.text
    return res.json()


def test_verification_off_keeps_payload_without_the_field_value(tmp_path) -> None:
    client = TestClient(
        create_app(
            Settings(
                env="test",
                database_url=engine_url(tmp_path, "v5off"),
                jwt_secret=SECRET,
                # evidence_verification_mode defaults to "off"
            )
        )
    )
    body = _register_ask(client, "কোষ কী?")
    assert body["verification_status"] is None  # additive field, default None


def test_verification_shadow_attaches_deterministic_status(tmp_path) -> None:
    client = TestClient(
        create_app(
            Settings(
                env="test",
                database_url=engine_url(tmp_path, "v5shadow"),
                jwt_secret=SECRET,
                evidence_verification_mode="shadow",
            )
        )
    )
    body = _register_ask(client, "কোষ কী?")
    assert body["verification_status"] in ("verified", "unverified")
    # shadow never blocks: the answer semantics are unchanged
    assert body["grounded"] in (True, False)


def test_enforce_mode_requires_explicit_approval_at_boot(tmp_path) -> None:
    with pytest.raises(RuntimeError, match="EVIDENCE_VERIFICATION_ENFORCE_APPROVED"):
        create_app(
            Settings(
                env="test",
                database_url=engine_url(tmp_path, "v5enforce"),
                jwt_secret=SECRET,
                evidence_verification_mode="enforce",
            )
        )
    # explicit approval boots (behaviour still deterministic-only)
    app = create_app(
        Settings(
            env="test",
            database_url=engine_url(tmp_path, "v5enforce2"),
            jwt_secret=SECRET,
            evidence_verification_mode="enforce",
            evidence_verification_enforce_approved=True,
        )
    )
    assert app is not None


def test_unknown_verification_mode_refuses_boot(tmp_path) -> None:
    with pytest.raises(RuntimeError, match=r"off\|shadow\|enforce"):
        create_app(
            Settings(
                env="test",
                database_url=engine_url(tmp_path, "v5bad"),
                jwt_secret=SECRET,
                evidence_verification_mode="yolo",
            )
        )
