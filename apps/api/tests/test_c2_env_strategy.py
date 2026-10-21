"""C-18: the documented environment strategy matches the manifests.

The audit found the strategy was documented in several places (compose
profiles, `deploy/DEPLOYMENT.md`, `docs/architecture/DATABASE_ARCHITECTURE.md`)
but nothing tied them together or proved the compose file even renders, and
`docs/architecture/ENVIRONMENT_STRATEGY.md` did not exist.

This module is that tie: it renders the compose file with an empty env file
(so a developer's `.env` cannot change the answer), then checks the render
against the document -- profiles, services, documented defaults, the loopback
port posture -- and checks the environment names the document uses against
`Settings`/`PRODUCTION_ENVS`. A documented-but-nonexistent profile, or a
profile that exists but is undocumented, fails the build.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from bangla_gpt_api.config import PRODUCTION_ENVS, Settings

REPO = Path(__file__).resolve().parents[3]
COMPOSE = REPO / "docker-compose.yml"
DOC = REPO / "docs" / "architecture" / "ENVIRONMENT_STRATEGY.md"

#: The topology the document promises (mirrors the doc's profile table).
EXPECTED_PROFILES = {"core", "worker", "web", "tls", "postgres", "monitoring", "backup"}
EXPECTED_SERVICES = {
    "api",
    "redis",
    "worker",
    "web",
    "caddy",
    "postgres",
    "pgbackrest",
    "prometheus",
    "grafana",
    "backup",
}
#: Defaults an operator can rely on when no .env exists (checked in the render).
EXPECTED_API_DEFAULTS = {
    "ENV": "production",
    "RATE_LIMIT_BACKEND": "redis",
    "JOBS_BACKEND": "inline",
}

docker_missing = shutil.which("docker") is None
requires_docker = pytest.mark.skipif(
    docker_missing,
    reason="docker CLI is not installed in this environment; the manifest checks need it "
    "(CI runs them in a job that has Docker)",
)


def _run(args: list[str], tmp_path: Path) -> subprocess.CompletedProcess[str]:
    empty_env = tmp_path / "empty.env"
    empty_env.write_text("", encoding="utf-8")
    return subprocess.run(
        # S607: "docker" comes off PATH on purpose -- the CLI is the subject
        # under test, and its absolute location differs per host.
        ["docker", "compose", "--env-file", str(empty_env), *args],  # noqa: S607
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )


class _Compose:
    """One render, shared by the module: compose CLI calls are ~40s each."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        profile_flags = [flag for name in sorted(EXPECTED_PROFILES) for flag in ("--profile", name)]
        quiet = _run(["config", "-q"], tmp_path)
        self.quiet_returncode = quiet.returncode
        self.quiet_stderr = quiet.stderr
        full = _run([*profile_flags, "config", "--format", "json"], tmp_path)
        assert full.returncode == 0, full.stderr
        self.doc: dict = json.loads(full.stdout)
        profiles = _run(["config", "--profiles"], tmp_path)
        self.profiles_output = profiles.stdout if profiles.returncode == 0 else ""


@pytest.fixture(scope="module")
def compose(tmp_path_factory) -> _Compose:
    return _Compose(tmp_path_factory.mktemp("compose"))


@pytest.fixture(scope="module")
def rendered(compose: _Compose) -> dict:
    return compose.doc


@requires_docker
def test_manifests_render(compose: _Compose) -> None:
    """`docker compose config -q` is the item's own verify command."""
    assert compose.quiet_returncode == 0, compose.quiet_stderr
    assert compose.quiet_stderr.strip() == "", compose.quiet_stderr


@requires_docker
def test_profile_list_is_the_documented_one(compose: _Compose) -> None:
    listed = {line.strip() for line in compose.profiles_output.splitlines() if line.strip()}
    assert listed == EXPECTED_PROFILES


@requires_docker
def test_rendered_topology_matches_the_document(rendered) -> None:
    assert set(rendered["services"]) == EXPECTED_SERVICES
    profiles: set[str] = set()
    for service in rendered["services"].values():
        profiles.update(service.get("profiles", []))
    assert profiles == EXPECTED_PROFILES


@requires_docker
def test_documented_defaults_survive_an_empty_environment(rendered) -> None:
    environment = rendered["services"]["api"]["environment"]
    for key, value in EXPECTED_API_DEFAULTS.items():
        assert environment.get(key) == value, f"API default {key} drifted"


@requires_docker
def test_api_listens_on_loopback_unless_the_operator_widens_it(rendered) -> None:
    ports = rendered["services"]["api"]["ports"]
    assert ports and ports[0]["host_ip"] == "127.0.0.1"
    assert str(ports[0]["target"]) == "8000"


@requires_docker
def test_healthchecks_are_declared_for_the_stateful_services(rendered) -> None:
    """The two services whose readiness gates a deploy must probe themselves."""
    for name in ("api", "postgres"):
        assert rendered["services"][name].get("healthcheck"), f"{name} lost its healthcheck"
    # redis carries no probe on purpose (no persistence, 64 MB cap); the
    # document says so and /ready is the readiness authority for it.
    assert "redis" not in rendered["services"] or not rendered["services"]["redis"].get(
        "healthcheck"
    )
    assert "deliberately has no healthcheck" in DOC.read_text(encoding="utf-8")


def test_the_document_has_the_topology_table_the_test_reads() -> None:
    text = DOC.read_text(encoding="utf-8")
    assert "docker compose config" in text
    for profile in EXPECTED_PROFILES:
        assert f"`{profile}`" in text, f"profile {profile} is undocumented"
    for name in ("development", "test", "staging", "production"):
        assert f"**{name}**" in text, f"environment {name} is undocumented"


def test_documented_profiles_table_matches_the_compose_services() -> None:
    """Parse the doc's profile table and compare it with the compose file."""
    text = DOC.read_text(encoding="utf-8")
    rows = re.findall(r"^\| `([a-z_]+)` \| ([^|]+) \|", text, flags=re.MULTILINE)
    documented = {
        profile: {name.strip().strip("`") for name in services.split(",")}
        for profile, services in rows
    }
    assert set(documented) == EXPECTED_PROFILES, documented

    compose_text = COMPOSE.read_text(encoding="utf-8")
    blocks: dict[str, str] = {}
    for match in re.finditer(r"^  ([a-z][a-z0-9_]*):$", compose_text, flags=re.MULTILINE):
        start = match.end()
        nxt = re.search(r"^  [a-z][a-z0-9_]*:$", compose_text[start:], flags=re.MULTILINE)
        blocks[match.group(1)] = compose_text[
            start : start + (nxt.start() if nxt else len(compose_text))
        ]
    assert set(blocks) >= EXPECTED_SERVICES

    for profile, services in documented.items():
        for service in services:
            assert service in blocks, f"{service} is documented under {profile} but is no service"
            assert f"profiles: [{profile}]" in blocks[service], (
                f"{service} does not declare the profile the document promises ({profile})"
            )


def test_environment_names_are_real_settings_values() -> None:
    assert "staging" in PRODUCTION_ENVS, "staging must keep production's strict boot posture"
    assert Settings(env="staging").is_production is True
    assert Settings(env="production").is_production is True
    assert Settings(env="development").is_production is False
    assert Settings(env="test").is_production is False


def test_env_examples_exist_and_stay_out_of_git() -> None:
    assert (REPO / ".env.example").exists()
    assert (REPO / ".env.production.example").exists()
    gitignore = (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in gitignore and ".env.*" in gitignore
    assert "!.env.example" in gitignore and "!.env.production.example" in gitignore


def test_document_points_at_the_existing_operational_docs() -> None:
    text = DOC.read_text(encoding="utf-8")
    for relative in ("../../deploy/DEPLOYMENT.md",):
        assert relative in text, f"{relative} is not referenced by the strategy document"
        target = (DOC.parent / relative).resolve()
        assert target.exists(), f"{relative} is referenced but missing"
