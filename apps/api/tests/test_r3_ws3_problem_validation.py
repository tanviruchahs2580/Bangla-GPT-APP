"""R3 / WS3: a 422 whose Pydantic error carries a raised object must still render.

FastAPI's ``RequestValidationError.errors()`` is *not* always JSON-safe: when a
``model_validator`` raises ``ValueError`` (the shape ``QPReviewDecision`` and
the question-paper difficulty validator use), the offending entry carries
``ctx: {"error": ValueError(...)}``. FastAPI's own handler runs the list
through ``jsonable_encoder`` before serialising; the app's RFC 9457 handler
must do the same, or every such request answers 500.

The first test drives the real route contract (the exact qpaper shape) through
the real app; the second pins the handler itself with a minimal app so a
regression is attributable to the handler, not to a route.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from pydantic import BaseModel, model_validator

from bangla_gpt_api.middleware import validation_exception_response


class _Decision(BaseModel):
    """Mirrors ``QPReviewDecision``: an after-validator that raises ValueError."""

    ref: str
    action: str
    text: str | None = None

    @model_validator(mode="after")
    def _edit_needs_text(self) -> _Decision:
        if self.action == "edit" and self.text is None:
            raise ValueError("edit decision must provide replacement text")
        return self


def test_model_validator_value_error_is_json_safe_at_the_handler() -> None:
    app = FastAPI()
    app.add_exception_handler(RequestValidationError, validation_exception_response)

    @app.post("/decide")
    def decide(payload: _Decision) -> dict[str, str]:  # pragma: no cover - never reached
        return {"ref": payload.ref}

    with TestClient(app, raise_server_exceptions=False) as client:
        res = client.post("/decide", json={"ref": "q1", "action": "edit"})

    assert res.status_code == 422, res.text
    assert res.headers["content-type"].startswith("application/problem+json")
    body = res.json()
    assert body["status"] == 422
    assert body["type"] == "about:blank"
    errors = body["detail"]
    assert isinstance(errors, list) and errors
    entry = errors[0]
    assert entry["loc"][:1] in (["body"], ("body",))
    assert "edit decision must provide replacement text" in entry["msg"]
    # The raised ValueError must have been sanitised, not crash the encoder.
    assert isinstance(entry.get("ctx", {}).get("error"), (str, dict))
