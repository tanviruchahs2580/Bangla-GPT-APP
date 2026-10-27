"""Deployment-configuration regression tests.

These are contract tests, not YAML lint. Each one pins a specific failure that
made the documented production stack unusable:

* `docker-compose.yml` did not pass PII_ENC_KEY / METRICS_* / TRUST_PROXY_HEADERS
  into the api container, so following the runbook produced a container that
  refused to boot ("Refusing to start: insecure production configuration").
* The api healthcheck and the release gate probed `/health`, which returns the
  constant {"status":"ok"} -- green while the database, cache and LLM provider
  were all down.
* `apps/web/.dockerignore` did not exist while its Dockerfile runs `COPY . .`,
  so a locally-created `.env.local` (a real VERCEL_OIDC_TOKEN) entered the
  build stage and was exported to the Actions cache by mode=max.
* The nginx config buffered the SSE stream and dropped the security headers on
  every static asset.
"""

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
COMPOSE = ROOT / "docker-compose.yml"
API_DOCKERFILE = ROOT / "Dockerfile"
WEB_DOCKERFILE = ROOT / "apps" / "web" / "Dockerfile"
NGINX = ROOT / "apps" / "web" / "deploy" / "nginx.conf"
NGINX_SNIPPET = ROOT / "apps" / "web" / "deploy" / "security-headers.conf"
ROOT_DOCKERIGNORE = ROOT / ".dockerignore"
WEB_DOCKERIGNORE = ROOT / "apps" / "web" / ".dockerignore"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# docker-compose: the production stack must actually be able to start
# ---------------------------------------------------------------------------


def _api_env_keys() -> set[str]:
    """Keys under the api service's `environment:` block."""
    text = _text(COMPOSE)
    start = text.index("\n  api:")
    # Up to the next top-level service key.
    end = text.index("\n  redis:", start)
    block = text[start:end]
    keys = set()
    for line in block.splitlines():
        match = re.match(r"\s{6}([A-Z][A-Z0-9_]*):", line)
        if match:
            keys.add(match.group(1))
    return keys


def test_compose_passes_the_boot_guard_required_variables() -> None:
    """The boot guard refuses to start without these, so compose must set them."""
    keys = _api_env_keys()
    for required in (
        "PII_ENC_KEY",  # _validate_pii -> RuntimeError
        "METRICS_REQUIRE_AUTH",  # _validate_metrics -> RuntimeError
        "METRICS_TOKEN",
        "JWT_SECRET",
        "ADMIN_EMAIL",
        "ADMIN_PASSWORD",
        "ALLOWED_ORIGINS",
    ):
        assert required in keys, (
            f"{required} is absent from the api service environment; the production "
            "boot guard refuses to start without it, so the documented compose "
            "stack cannot boot"
        )


def test_compose_exposes_the_proxy_trust_switch() -> None:
    """Behind Caddy/nginx every client would otherwise share one rate-limit bucket."""
    assert "TRUST_PROXY_HEADERS" in _api_env_keys()


def test_compose_passes_the_per_user_ai_budget() -> None:
    """Unset means 0, which disables the budget and leaves generation unmetered."""
    assert "AI_MONTHLY_BUDGET_USD_PER_USER" in _api_env_keys()


def test_compose_api_healthcheck_probes_readiness() -> None:
    """/health is a constant; only /ready actually probes dependencies."""
    block = _text(COMPOSE)[_text(COMPOSE).index("\n  api:") : _text(COMPOSE).index("\n  redis:")]
    assert "/ready" in block, "the api healthcheck must not use the constant /health"
    assert "/health'" not in block


def test_redis_has_a_healthcheck_so_depends_on_can_wait_for_it() -> None:
    text = _text(COMPOSE)
    redis = text[text.index("\n  redis:") : text.index("\n  worker:")]
    assert "healthcheck:" in redis, (
        "the api depends on redis being reachable; without a healthcheck "
        "`condition: service_healthy` cannot be satisfied"
    )
    assert "ping" in redis


def test_api_waits_for_a_healthy_redis() -> None:
    """`service_started` lets the API boot before Redis accepts connections."""
    text = _text(COMPOSE)
    assert re.search(r"depends_on:\s*\n\s*redis:\s*\n\s*condition: service_healthy", text)


# ---------------------------------------------------------------------------
# Dockerfile
# ---------------------------------------------------------------------------


def test_api_dockerfile_healthcheck_uses_ready() -> None:
    assert "/ready" in _text(API_DOCKERFILE)
    assert "/health'" not in _text(API_DOCKERFILE)


def test_api_dockerfile_worker_timeout_exceeds_worst_case_generation() -> None:
    """gunicorn SIGKILLs a worker past --timeout.

    LLM_TIMEOUT_SECONDS (30) x LLM_MAX_RETRIES (2) plus backoff already exceeds
    the old 60s, so a slow but healthy generation could be killed mid-answer.
    """
    text = _text(API_DOCKERFILE)
    timeout = int(re.search(r"--timeout (\d+)", text).group(1))
    assert timeout >= 120, f"worker timeout {timeout}s is shorter than the LLM budget"


def test_api_dockerfile_declares_version_and_revision_labels() -> None:
    """docs/operations/PRODUCTION_DEPLOYMENT.md documented an APP_VERSION build-arg
    that no ARG declared, so the flag was silently ignored."""
    text = _text(API_DOCKERFILE)
    assert "ARG APP_VERSION" in text
    assert "ARG APP_REVISION" in text
    assert "org.opencontainers.image.revision" in text


def test_api_dockerfile_installs_dependencies_before_copying_source() -> None:
    """Otherwise every one-line source edit re-resolves every wheel."""
    text = _text(API_DOCKERFILE)
    install = text.index("pip install")
    src_copy = text.index("COPY apps/api/src")
    assert install < src_copy, (
        "pip install must precede the source COPY or the dependency layer is "
        "invalidated by every source change"
    )


def test_api_dockerfile_still_installs_the_real_package_after_the_stub() -> None:
    """The stub-package trick needs a second, no-deps install to be sound."""
    assert "--no-deps ./apps/api" in _text(API_DOCKERFILE)


# ---------------------------------------------------------------------------
# Build-context secret hygiene
# ---------------------------------------------------------------------------


def test_web_build_context_excludes_env_files() -> None:
    """The web Dockerfile runs `COPY . .`; without this, a local .env.local
    holding a real VERCEL_OIDC_TOKEN enters the build stage."""
    assert WEB_DOCKERIGNORE.exists(), (
        "apps/web/.dockerignore is required: the web Dockerfile does COPY . ."
    )
    rules = _text(WEB_DOCKERIGNORE).splitlines()
    assert any(r.strip() == ".env" for r in rules)
    assert any(r.strip() == ".vercel" for r in rules)
    assert any(r.strip() == "node_modules" for r in rules)


def test_root_build_context_excludes_all_secret_material() -> None:
    rules = {r.strip() for r in _text(ROOT_DOCKERIGNORE).splitlines()}
    for required in (
        "**/.env",
        "**/.env.*",
        "**/*.pem",
        "**/*.key",
        ".mailpit",
        ".venv",
        "**/node_modules",
    ):
        assert required in rules, f"{required} must be excluded from the build context"


def test_root_dockerignore_keeps_the_examples() -> None:
    """A blanket .env* rule would drop the documented template files."""
    rules = [
        r.strip() for r in _text(ROOT_DOCKERIGNORE).splitlines() if not r.strip().startswith("#")
    ]
    assert "!**/.env.example" in rules
    assert "!**/.env.production.example" in rules


def test_release_web_cache_does_not_export_every_build_stage() -> None:
    """cache-to mode=max writes intermediate stages, which is how build-context
    contents become readable to anyone with actions:read."""
    workflow = _text(ROOT / ".github" / "workflows" / "release.yml")
    web_cache = re.search(r"scope=web.*", workflow)
    assert web_cache, "the web build cache line disappeared"
    assert "mode=max" not in web_cache.group(0)


# ---------------------------------------------------------------------------
# nginx: streaming and header behaviour
# ---------------------------------------------------------------------------


def test_nginx_does_not_buffer_the_sse_stream() -> None:
    """Buffering delivers the whole answer in one blob, so the tutor stops
    streaming entirely while /health still looks healthy."""
    api = _text(NGINX)[_text(NGINX).index("location /api/") :]
    api = api[: api.index("location / {")]
    assert "proxy_buffering off" in api
    assert "X-Accel-Buffering" in api
    assert "proxy_read_timeout 3600s" in api, (
        "a 75s read timeout cut off long generations mid-stream"
    )


def test_every_nginx_location_includes_the_security_header_snippet() -> None:
    """nginx drops inherited add_header once a location declares its own.

    So the headers live in a snippet that each block includes; a location that
    forgets the include silently serves its responses without them.
    """
    text = _text(NGINX)
    blocks = re.findall(r"location\s+[^{]+\{", text)
    assert blocks, "no location blocks found; the config shape changed"
    for header in blocks:
        body = _nginx_location(text, header.rstrip("{").strip())
        assert "security-headers.conf" in body, (
            f"{header.strip()} does not include the security headers"
        )


def test_security_header_snippet_ships_the_full_set() -> None:
    snippet = _text(NGINX_SNIPPET)
    for header in (
        "X-Content-Type-Options",
        "X-Frame-Options",
        "Referrer-Policy",
        "Content-Security-Policy",
    ):
        assert header in snippet, f"{header} missing from the snippet"
    # The SPA reads its token from localStorage, so no inline script allowance.
    assert "script-src 'self'" in snippet
    assert "unsafe-eval" not in snippet


def test_web_dockerfile_installs_the_snippet() -> None:
    """The snippet is only effective if it reaches /etc/nginx/snippets/."""
    dockerfile = _text(WEB_DOCKERFILE)
    assert "security-headers.conf /etc/nginx/snippets/" in dockerfile


def test_nginx_does_not_cache_the_service_worker() -> None:
    """A cached sw.js outlives the deploy that wrote it."""
    assert "no-cache" in _nginx_location(_text(NGINX), "location = /sw.js")


def _nginx_location(text: str, header: str) -> str:
    """Body of one nginx location block, braces balanced."""
    start = text.index(header)
    depth = 0
    for index in range(start, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    raise AssertionError(f"unbalanced location block: {header}")


def test_ci_asserts_the_image_refuses_an_insecure_production_boot() -> None:
    """The container smoke runs with ENV=ci, which skips every boot guard.

    Without this step the image's most valuable property -- that it will not
    start in production with the default JWT secret -- is never executed, which
    is how a typo'd ENV booted insecurely in the first place.
    """
    workflow = _text(ROOT / ".github" / "workflows" / "ci.yml")
    assert "Refusing to start" in workflow, (
        "CI must assert that the image refuses an insecure production boot"
    )
    assert "prodction" in workflow, (
        "CI must cover the misspelled-ENV case, not only the exact 'production'"
    )
    assert "/ready" in workflow, "the container smoke must wait on /ready, not /health"


def test_nginx_immutable_cache_only_for_hashed_assets() -> None:
    text = _text(NGINX)
    # Vite content-hashes filenames under /assets/, so those are safe to pin
    # for a year. The un-hashed entry points must stay revalidated.
    assert "immutable" in _nginx_location(text, "location /assets/")
    assert "no-cache" in _nginx_location(text, "location = /index.html")


def test_nginx_compresses_the_spa_but_not_the_api_stream() -> None:
    text = _text(NGINX)
    assert "gzip on" in text
    # gzip_types must not be declared inside the /api/ block.
    api = text[text.index("location /api/") :]
    api = api[: api.index("location / {")]
    assert "gzip" not in api


@pytest.mark.parametrize(
    "path", [COMPOSE, NGINX, NGINX_SNIPPET, ROOT_DOCKERIGNORE, WEB_DOCKERIGNORE]
)
def test_config_files_are_utf8(path: Path) -> None:
    _text(path)


def test_vercel_headers_mirror_the_csp() -> None:
    """Vercel serves the SPA directly, so nginx's headers do not apply there."""
    vercel = json.loads(_text(ROOT / "apps" / "web" / "vercel.json"))
    assert "headers" in vercel, "the Vercel deployment ships no security headers"
    blob = json.dumps(vercel).lower()
    assert "content-security-policy" in blob
    assert "x-frame-options" in blob


def test_vercel_has_no_hardcoded_tunnel_host() -> None:
    """A quick tunnel was removed from the config; it must not come back."""
    blob = _text(ROOT / "apps" / "web" / "vercel.json").lower()
    assert "trycloudflare" not in blob
    assert "loca.lt" not in blob
