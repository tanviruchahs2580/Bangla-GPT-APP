"""Every operation's auth decision must be explicit in the served OpenAPI.

SEC-06 requires an explicit auth decision on every route. In the document
FastAPI generates, an operation with no security dependency simply *omits*
`security` -- indistinguishable from "authentication forgotten", which is how a
real bypass stays invisible.

AUD-0054: with 11 operations omitting the field, schemathesis reported a
critical "API accepts requests without authentication" against
POST /auth/resend-verification, an endpoint that is deliberately anonymous.
The tool was right that the contract was ambiguous, and wrong about behaviour.

These tests keep the declaration honest in both directions: everything listed
must exist and be marked public, and nothing may be public without being
listed -- the second is the property that would catch a forgotten guard.
"""

from __future__ import annotations

import pytest

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import PUBLIC_OPERATIONS, _normalise_path, create_app

_HTTP = {"get", "post", "put", "patch", "delete", "head", "options"}


@pytest.fixture(scope="module")
def spec(tmp_path_factory) -> dict:
    db = tmp_path_factory.mktemp("spec") / "openapi.db"
    app = create_app(Settings(env="development", database_url=f"sqlite:///{db.as_posix()}"))
    return app.openapi()


def _operations(spec: dict) -> dict[tuple[str, str], dict]:
    out = {}
    for path, item in spec.get("paths", {}).items():
        for method, op in item.items():
            if method.lower() in _HTTP:
                out[(method.lower(), _normalise_path(path))] = op
    return out


def test_spec_is_not_trivially_empty(spec):
    ops = _operations(spec)
    assert len(ops) > 100, f"expected the full route set, got {len(ops)}"


@pytest.mark.parametrize("entry", sorted(PUBLIC_OPERATIONS))
def test_every_declared_public_operation_exists_and_is_marked(spec, entry):
    ops = _operations(spec)
    assert entry in ops, f"PUBLIC_OPERATIONS lists {entry}, which is not in the spec"
    assert ops[entry].get("security") == [], f"{entry} is declared public but security is not []"


def test_no_operation_is_public_without_being_declared(spec):
    """The guard against a forgotten auth dependency.

    Any operation that ends up with `security: []` without appearing in
    PUBLIC_OPERATIONS is either a newly-anonymous route or a stale declaration.
    """
    declared = {(m.lower(), _normalise_path(p)) for m, p in PUBLIC_OPERATIONS}
    undeclared = {
        key for key, op in _operations(spec).items() if op.get("security") == []
    } - declared
    assert not undeclared, (
        f"these operations are public in the contract but not declared in "
        f"PUBLIC_OPERATIONS: {sorted(undeclared)}"
    )


def test_protected_operations_still_declare_security(spec):
    """The public marking must not have leaked onto protected routes."""
    declared = {(m.lower(), _normalise_path(p)) for m, p in PUBLIC_OPERATIONS}
    missing = {
        key for key, op in _operations(spec).items() if key not in declared and "security" not in op
    }
    assert not missing, (
        f"these operations declare no security requirement and are not listed as "
        f"publicly intentional: {sorted(missing)}"
    )


def test_trailing_slash_does_not_defeat_the_matching():
    assert _normalise_path("/status/") == "/status"
    assert _normalise_path("/status") == "/status"
    assert ("post", "/auth/resend-verification") in {
        (m.lower(), _normalise_path(p)) for m, p in PUBLIC_OPERATIONS
    }
