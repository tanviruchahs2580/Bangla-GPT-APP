"""F-066/F-169/F-124: contract guards for the route inventory, the version and
the static-asset cache policy.

Each guard exists because the audit found the artefact drifting from the code:
`docs/route_baseline.md` was a hand-captured snapshot, the API version had a
hardcoded fallback constant, and the cache headers lived only in prose.
"""

import importlib.metadata
import json
import re
import tomllib
from pathlib import Path

from bangla_gpt_api import config
from bangla_gpt_api.config import Settings
from bangla_gpt_api.main import create_app
from conftest import engine_url

REPO_ROOT = Path(__file__).resolve().parents[3]
ROUTE_BASELINE = REPO_ROOT / "docs" / "route_baseline.md"

#: Routes FastAPI serves without listing them in the schema, plus /metrics
#: (`include_in_schema=False`). The baseline file documents them in its header.
NON_SCHEMA_ROUTES = frozenset(
    {
        ("GET", "/openapi.json"),
        ("GET", "/docs"),
        ("GET", "/docs/oauth2-redirect"),
        ("GET", "/redoc"),
        ("GET", "/metrics"),
    }
)

_HTTP_METHODS = ("get", "post", "put", "patch", "delete", "head", "options")


def _settings(tmp_path) -> Settings:
    return Settings(
        env="test",
        database_url=engine_url(tmp_path, "w2contract"),
        jwt_secret="w2-contract-secret-0123456789abcdef",
    )


def test_route_baseline_matches_the_served_schema(tmp_path) -> None:
    """The checked-in inventory must equal the app's own route set.

    README points readers at this file; a route added or removed without
    regenerating it is a stale contract (F-066, API-07).
    """
    app = create_app(_settings(tmp_path))
    spec = app.openapi()
    served = {
        (method.upper(), path)
        for path, item in spec["paths"].items()
        for method in item
        if method.lower() in _HTTP_METHODS
    }
    text = ROUTE_BASELINE.read_text(encoding="utf-8")
    documented = {
        (method, path)
        for method, path in re.findall(
            r"^\|\s*\d+\s*\|\s*([A-Z]+)\s*\|\s*`([^`]+)`\s*\|", text, re.M
        )
    }
    assert documented - served - NON_SCHEMA_ROUTES == set(), (
        "baseline lists routes the app no longer serves"
    )
    assert served - documented == set(), "routes missing from docs/route_baseline.md"


def test_the_version_fallback_is_the_release_manifest(monkeypatch) -> None:
    """Without installed metadata the version reads pyproject, not a literal.

    The old fallback was a hardcoded `0.9.2` that drifted from the manifest
    (F-169); this pins the fallback to the single source of truth.
    """
    pyproject = tomllib.loads((REPO_ROOT / "apps" / "api" / "pyproject.toml").read_text("utf-8"))
    expected = pyproject["project"]["version"]
    assert config._project_version() == expected

    def _no_metadata(name: str) -> str:
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, "version", _no_metadata)
    assert config._get_version() == expected


def test_the_served_spec_reports_the_settings_version(tmp_path) -> None:
    settings = _settings(tmp_path)
    app = create_app(settings)
    assert app.openapi()["info"]["version"] == settings.version


def _cache_headers(rules: list[dict], source: str) -> dict[str, str]:
    for rule in rules:
        if rule["source"] == source:
            return {header["key"]: header["value"] for header in rule["headers"]}
    raise AssertionError(f"no header rule for {source}")


def test_vercel_serves_hashed_assets_immutably_and_the_shell_revalidated() -> None:
    """F-124/PERF-07: the CDN path must match the nginx path."""
    config_json = json.loads((REPO_ROOT / "apps" / "web" / "vercel.json").read_text("utf-8"))
    assets = _cache_headers(config_json["headers"], "/assets/(.*)")
    assert assets["Cache-Control"] == "public, max-age=31536000, immutable"
    for shell in ("/index.html", "/sw.js"):
        assert _cache_headers(config_json["headers"], shell)["Cache-Control"] == "no-cache"


def test_nginx_serves_hashed_assets_immutably_and_the_shell_revalidated() -> None:
    text = (REPO_ROOT / "apps" / "web" / "deploy" / "nginx.conf").read_text("utf-8")

    def block(location: str) -> str:
        match = re.search(rf"location {re.escape(location)} \{{(.*?)\n    \}}", text, re.S)
        assert match is not None, f"no {location} block in nginx.conf"
        return match.group(1)

    assets = block("/assets/")
    assert "expires 1y" in assets
    assert "immutable" in assets
    assert "no-cache" in block("= /index.html")
    assert "no-cache" in block("= /sw.js")
