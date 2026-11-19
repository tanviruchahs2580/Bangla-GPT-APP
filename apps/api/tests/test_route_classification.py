"""T-11 guard: the route classification file must describe the served surface.

``tests/data/route_classification.json`` maps every runtime operation to one
of ``public | authenticated | optional-auth | role-restricted |
production-token-gated``. Without this file, "which routes need which auth"
lives only in scattered handler signatures, and a new route can ship
unclassified. Two failure modes are guarded:

* a served operation (the OpenAPI document plus the runtime-only ``/metrics``
  route, which is deliberately outside the schema -- F-30) missing from the
  file, or a file entry naming an operation that no longer exists;
* an entry whose class is not one of the allowed values, or a ``public``
  entry that disagrees with ``main.PUBLIC_OPERATIONS`` -- the deliberate
  public-operation set the auth matrix test already pins.

The file's ``roles`` column is documentation of intent, not enforcement; the
runtime authorization behaviour is exercised by the tenancy/owner suites.
"""

from __future__ import annotations

import json
from pathlib import Path

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import PUBLIC_OPERATIONS, _normalise_path, create_app

FILE = Path(__file__).parent / "data" / "route_classification.json"
ALLOWED_CLASSES = {
    "public",
    "authenticated",
    "optional-auth",
    "role-restricted",
    "production-token-gated",
}
# /metrics exists at runtime (routers/system.py) but is intentionally absent
# from the OpenAPI document (F-30): it is an operational surface, not an API
# contract. The classification file records it so it cannot escape inventory.
RUNTIME_ONLY_OPERATIONS = {("/metrics", "GET")}


def _served_operations() -> set[tuple[str, str]]:
    app = create_app(Settings(env="test", database_url="sqlite://", jwt_secret="x" * 48))
    doc = app.openapi()
    ops = {
        (path, method.upper())
        for path, methods in doc["paths"].items()
        for method in methods
        if method.lower() in {"get", "post", "put", "patch", "delete"}
    }
    return ops | RUNTIME_ONLY_OPERATIONS


def test_classification_file_covers_every_served_operation_and_no_more():
    entries = json.loads(FILE.read_text(encoding="utf-8"))["operations"]
    filed = {(e["path"], e["method"].upper()) for e in entries}
    served = _served_operations()
    missing = sorted(served - filed)
    stale = sorted(filed - served)
    assert not missing, f"served operations absent from the classification file: {missing}"
    assert not stale, f"classification file names operations that no longer exist: {stale}"


def test_every_entry_has_an_allowed_class():
    entries = json.loads(FILE.read_text(encoding="utf-8"))["operations"]
    bad = [
        (e["path"], e["method"], e["class"]) for e in entries if e["class"] not in ALLOWED_CLASSES
    ]
    assert not bad, f"entries with an unknown class: {bad}"


def test_public_entries_agree_with_the_deliberate_public_operation_set():
    entries = json.loads(FILE.read_text(encoding="utf-8"))["operations"]
    file_public = {(e["path"], e["method"].upper()) for e in entries if e["class"] == "public"}
    main_public = {
        (path, method.upper())  # PUBLIC_OPERATIONS stores lowercase methods
        for method, path in PUBLIC_OPERATIONS
    }
    assert file_public == main_public, (
        "the classification file's public set and main.PUBLIC_OPERATIONS "
        f"disagree: file-only={sorted(file_public - main_public)}, "
        f"main-only={sorted(main_public - file_public)}"
    )


def test_production_token_gated_entry_is_metrics_only():
    entries = json.loads(FILE.read_text(encoding="utf-8"))["operations"]
    gated = [
        (e["path"], e["method"].upper()) for e in entries if e["class"] == "production-token-gated"
    ]
    assert gated == [("/metrics", "GET")], gated


def test_normalise_path_contract_still_holds_for_the_file():
    """Every file path, normalised, must appear verbatim in the served set --
    a trailing-slash spelling in the file would silently compare unequal."""
    entries = json.loads(FILE.read_text(encoding="utf-8"))["operations"]
    served = _served_operations()
    for e in entries:
        key = (e["path"], e["method"].upper())
        if key not in served:
            raise AssertionError(
                f"entry {key} (normalised {_normalise_path(e['path'])}) is not served"
            )
