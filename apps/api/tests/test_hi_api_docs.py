"""H-01 / AUD-HI-05 and AUD-HI-03: docs and dashboards cannot drift.

Two guards, both of them mechanically derivable, both of them previously absent:

* ``docs/API.md`` is generated from the served OpenAPI schema and a drift check
  fails when the committed file differs (run in a subprocess, exactly as CI
  does, so no test-session state can make it pass);
* every ``bgpt_*`` metric a dashboard or alert rule queries must exist in the
  rendered Prometheus registry — the defect that left four Grafana panels
  permanently empty.

Plus negative tests: a guard that cannot fail is not a guard.
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
API_DIR = REPO_ROOT / "apps" / "api"
SCRIPTS = API_DIR / "scripts"


def _load(module_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(module_name, SCRIPTS / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gen_api_docs():
    return _load("hi_gen_api_docs", "gen_api_docs.py")


@pytest.fixture(scope="module")
def check_dashboards():
    return _load("hi_check_dashboards", "check_dashboards.py")


# --- API reference drift ---------------------------------------------------


def test_committed_api_reference_matches_the_served_schema() -> None:
    """The real check: regenerate in memory and diff (subprocess, like CI)."""
    result = subprocess.run(
        [sys.executable, "scripts/gen_api_docs.py", "--check"],
        cwd=API_DIR,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert "matches the OpenAPI schema" in result.stdout


def test_drift_check_fails_when_the_committed_file_is_stale(
    gen_api_docs, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stale = tmp_path / "API.md"
    stale.write_text("# API Reference\n\nA hand-edited file that drifted.\n", encoding="utf-8")
    monkeypatch.setattr(gen_api_docs, "DOC_PATH", stale)
    # A minimal spec stands in for the app build: the comparison is what is
    # under test, not the schema extraction (covered by the subprocess test).
    monkeypatch.setattr(
        gen_api_docs,
        "build_spec",
        lambda: {"openapi": "3.1.0", "info": {"title": "T", "version": "0"}, "paths": {}},
    )
    assert gen_api_docs.main(["--check"]) == 1
    # And it passes once the file is regenerated: the check is not a tripwire.
    assert gen_api_docs.main([]) == 0
    assert gen_api_docs.main(["--check"]) == 0


def test_api_reference_states_the_coded_error_contract(gen_api_docs) -> None:
    """The old hand-written file claimed ``{"detail": "..."}`` for everything."""
    text = (REPO_ROOT / "docs" / "API.md").read_text(encoding="utf-8")
    assert "GENERATED FILE" in text
    assert '"code"' in text and "Business-rule error codes" in text
    assert "no_student_profile" in text or "email_taken" in text
    # The catalog is rendered from code, so every catalogued code appears.
    from bangla_gpt_api.routers._error_contract import ERROR_CATALOG

    for code in ERROR_CATALOG:
        assert f"`{code}`" in text, f"{code} missing from the generated reference"


# --- dashboard / alert metric lint ----------------------------------------


def test_dashboard_and_alert_metrics_are_exported(check_dashboards) -> None:
    assert check_dashboards.main() == 0


def test_metric_lint_fails_on_an_unknown_metric(
    check_dashboards, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dashboard_dir = tmp_path / "dashboards"
    dashboard_dir.mkdir()
    (dashboard_dir / "broken.json").write_text(
        json.dumps(
            {
                "title": "broken",
                "panels": [
                    {"title": "ghost", "targets": [{"expr": "rate(bgpt_ghost_metric_total[5m])"}]}
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(check_dashboards, "DASHBOARD_DIR", dashboard_dir)
    monkeypatch.setattr(check_dashboards, "ALERT_FILE", tmp_path / "missing.yml")
    assert check_dashboards.main() == 1

    # A reference to a real exported series passes, so the lint is not
    # failing merely because it was pointed at a temporary directory.
    (dashboard_dir / "broken.json").write_text(
        json.dumps(
            {
                "title": "ok",
                "panels": [
                    {"title": "ok", "targets": [{"expr": "rate(bgpt_ai_answers_total[5m])"}]}
                ],
            }
        ),
        encoding="utf-8",
    )
    assert check_dashboards.main() == 0
