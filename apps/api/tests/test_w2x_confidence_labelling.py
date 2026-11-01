"""F-119 / LLM-10: the served `confidence` number is labelled a heuristic.

The value is a blend of retrieval score and source count with no measured
calibration against answer correctness, so presenting it without a qualifier
reads as a probability statement. The API's presentation surface is the
OpenAPI contract: every confidence-bearing response field and the app summary
must carry the heuristic qualifier, and the schema must not claim calibration.
"""

from __future__ import annotations

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app
from conftest import engine_url


def _openapi(tmp_path) -> dict:
    settings = Settings(
        env="test",
        database_url=engine_url(tmp_path, "w2xconf"),
        jwt_secret="w2x-confidence-secret-0123456789ab",
    )
    return create_app(settings).openapi()


def _confidence_fields(spec: dict) -> list[tuple[str, dict]]:
    fields: list[tuple[str, dict]] = []
    for name, schema in spec["components"]["schemas"].items():
        for prop_name, prop in schema.get("properties", {}).items():
            if "confidence" in prop_name:
                fields.append((f"{name}.{prop_name}", prop))
    return fields


def test_every_confidence_field_is_labelled_a_heuristic(tmp_path) -> None:
    fields = _confidence_fields(_openapi(tmp_path))
    assert fields, "no confidence field is served; the guard would never run"
    for qualified_name, prop in fields:
        description = (prop.get("description") or "").lower()
        assert "heuristic" in description, f"{qualified_name} is not labelled heuristic"
        assert "not a calibrated" in description, (
            f"{qualified_name} does not deny being a calibrated figure"
        )


def test_the_api_summary_repeats_the_heuristic_qualifier(tmp_path) -> None:
    info = _openapi(tmp_path)["info"]
    assert "confidence" in info["description"].lower()
    assert "heuristic" in info["description"].lower()
    assert "calibrated probability" in info["description"].lower()
