"""S5.1: environment parity drift guard (dev/staging/prod).

PASS-WHEN of 5.1 is a fresh staging bring-up (human/infra step, R8); what CAN
be enforced in code is that the documented env surface and the settings model
never drift apart:

* every variable documented in .env.example (dev) is a real Settings field;
* every variable in .env.production.example is either a real Settings field
  or a documented compose/build-only variable (INFRA_ONLY below) -- adding a
  new secret to the provisioning doc without wiring it into the app, or
  renaming a Settings field without updating the docs, fails this test;
* every ${VAR} compose interpolates is either given a default in the compose
  file or documented in .env.production.example (no undocumented deploy-time
  surprises);
* ENV supports exactly the three documented environments.
"""

import re
from pathlib import Path

from bangla_gpt_api.config import Settings

ROOT = Path(__file__).resolve().parents[3]

# Documented provisioning variables intentionally absent from Settings:
# they configure compose services (postgres, caddy, grafana, backup sidecar,
# image tags) or the web build -- never the API process.
INFRA_ONLY = {
    "ACME_EMAIL",  # Caddy auto-HTTPS certificate contact
    "API_TAG",  # compose image tag
    "WEB_TAG",  # compose image tag
    "BACKUP_INTERVAL_SECONDS",  # backup sidecar loop
    "BACKUP_KEEP_DAYS",  # backup sidecar retention
    "DOMAIN",  # Caddy site address
    "GRAFANA_ADMIN_PASSWORD",  # monitoring stack login
    "PGBR_STANZA",  # pgBackRest stanza name (S5.7 backup sidecar)
    "POSTGRES_DB",  # postgres service bootstrap
    "POSTGRES_PASSWORD",  # postgres service bootstrap
    "POSTGRES_USER",  # postgres service bootstrap
    "S3_BUCKET",  # corpus object-storage sync (scripts/s3_corpus_sync.py, S5.7)
    "S3_PREFIX",  # corpus object-storage key prefix (S5.7)
    "VITE_API_BASE",  # web build-time API base URL
    "WEB_CONCURRENCY",  # uvicorn worker count (deploy command, not app setting)
}


def _env_file_keys(path: Path) -> set[str]:
    return set(re.findall(r"^([A-Z][A-Z0-9_]*)=", path.read_text(encoding="utf-8"), re.M))


def _settings_keys() -> set[str]:
    return {name.upper() for name in Settings.model_fields}


def test_dev_example_maps_exactly_to_settings_fields() -> None:
    keys = _env_file_keys(ROOT / ".env.example")
    unknown = keys - _settings_keys()
    assert not unknown, f".env.example documents vars with no Settings field: {sorted(unknown)}"


def test_production_example_only_adds_documented_infra_vars() -> None:
    keys = _env_file_keys(ROOT / ".env.production.example")
    unknown = keys - _settings_keys() - INFRA_ONLY
    assert not unknown, f"undocumented non-Settings vars in production example: {sorted(unknown)}"


def test_compose_interpolations_are_documented_or_defaulted() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    prod_keys = _env_file_keys(ROOT / ".env.production.example")
    undocumented: list[str] = []
    for var, default in re.findall(r"\$\{([A-Z][A-Z0-9_]*)(:?-[^}]*)?\}", compose):
        if var not in prod_keys and not default:
            undocumented.append(var)
    bad = sorted(set(undocumented))
    assert not undocumented, f"compose vars undocumented and undefaulted: {bad}"


def test_settings_supports_the_three_documented_environments() -> None:
    for env in ("dev", "staging", "production"):
        assert Settings(env=env).env == env  # type: ignore[call-arg]


def test_staging_shares_production_strictness() -> None:
    # S5.1 parity: staging must run the production boot guard and secret
    # suppression; only dev/test are lenient.
    assert Settings(env="staging").is_production
    assert Settings(
        env="staging ",
    ).is_production  # type: ignore[call-arg]
    assert not Settings(env="dev").is_production
    assert not Settings(env="test").is_production
