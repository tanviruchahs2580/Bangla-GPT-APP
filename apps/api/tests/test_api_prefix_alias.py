"""The ``/api`` prefix alias — the APK's login path (FE-mobile parity).

The distributed Android WebView bakes ``VITE_API_BASE`` (an absolute URL
that ends in ``/api``) and has no server-side proxy: it calls
``<origin>/api/auth/login`` directly. The web app never sends a prefixed
path — Vercel's edge proxy strips ``/api`` before forwarding
(``apps/web/src/lib/apiProxy.ts``), mirroring the vite dev proxy — so the
alias below is invisible to it.

These tests pin the contract: every ``/api``-prefixed request must reach
the real route (a wrong-credential login is 401, never 404), CORS
preflight for the Capacitor origin must pass on an aliased path, and
unprefixed paths must behave exactly as before.
"""

from fastapi.testclient import TestClient

from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app
from conftest import engine_url

SECRET = "x" * 48
PASSWORD = "test-password-123"

#: The origins a Capacitor WebView actually sends (Android → https scheme,
#: iOS → capacitor scheme). Both are in the live ALLOWED_ORIGINS already.
APK_ORIGINS = ["https://localhost", "capacitor://localhost"]


def make_client(tmp_path, **overrides) -> TestClient:
    settings = Settings(
        env="test",
        database_url=engine_url(tmp_path, "apialias"),
        jwt_secret=SECRET,
        admin_email="root@example.com",
        admin_password=PASSWORD,
        force_admin_password_change=False,
        allowed_origins=",".join(APK_ORIGINS),
        **overrides,
    )
    return TestClient(create_app(settings))


def test_apk_login_alias_reaches_the_real_route(tmp_path) -> None:
    """A wrong-credential login through the alias is 401 — proof the route
    executed. The pre-fix behaviour was 404, which is the field-reported
    APK login failure."""
    client = make_client(tmp_path)
    response = client.post(
        "/api/auth/login",
        json={"email": "nobody@example.com", "password": "wrong"},
    )
    assert response.status_code == 401


def test_unprefixed_login_unchanged(tmp_path) -> None:
    client = make_client(tmp_path)
    response = client.post(
        "/auth/login",
        json={"email": "nobody@example.com", "password": "wrong"},
    )
    assert response.status_code == 401


def test_health_alias(tmp_path) -> None:
    client = make_client(tmp_path)
    assert client.get("/api/health").status_code == 200
    assert client.get("/health").status_code == 200


def test_cors_preflight_for_the_capacitor_origin_on_an_aliased_path(tmp_path) -> None:
    """Android Capacitor sends Origin ``https://localhost``; the preflight
    must be answered by CORS (which sits OUTSIDE the alias middleware) and
    echo the origin back."""
    client = make_client(tmp_path)
    response = client.options(
        "/api/auth/login",
        headers={
            "Origin": "https://localhost",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://localhost"


def test_single_strip_no_double_alias(tmp_path) -> None:
    """/api/api/health strips once to /api/health — a path with no route."""
    client = make_client(tmp_path)
    assert client.get("/api/api/health").status_code == 404


# --- T-25 / BC-4: the /v1 additive alias --------------------------------------


def test_v1_alias_serves_the_same_operations(tmp_path) -> None:
    """Every legacy system path is mirrored under /v1 with the same status."""
    client = make_client(tmp_path)
    legacy = client.get("/health")
    alias = client.get("/v1/health")
    assert legacy.status_code == alias.status_code == 200
    assert alias.json() == legacy.json()


def test_v1_alias_unauthenticated_denial_matches_legacy(tmp_path) -> None:
    client = make_client(tmp_path)
    assert client.get("/v1/users/me").status_code == 401
    assert client.get("/users/me").status_code == 401


def test_v1_alias_absent_from_the_openapi_document(tmp_path) -> None:
    """ADR-0013: the alias is transport-only; the document keeps ONE canonical
    surface so operation IDs stay unique and clients do not double-generate."""
    client = make_client(tmp_path)
    doc = client.get("/openapi.json").json()
    v1_paths = [p for p in doc["paths"] if p.startswith("/v1")]
    assert not v1_paths, f"/v1 leaked into the OpenAPI document: {v1_paths[:5]}"
