"""Every metric a dashboard or alert rule queries must actually be exported.

AUD-HI-03 (and its I-02 sibling) found the committed Grafana dashboard
querying ``http_request_duration_seconds_bucket`` / ``gemini_generate_latency_ms``
while the exporter registered ``bgpt_http_request_duration_seconds`` and no
``gemini_*`` series at all: four panels rendered empty, so "dashboards as code"
provided no signal while looking correct in review. A naming drift like that is
invisible to every other gate -- YAML and JSON parse fine, the app starts fine.

How this checks: it renders the application's own registry with
``prometheus_client.generate_latest`` (the same exposition a scrape gets) and
collects the sample names from it, then extracts every ``bgpt_*`` identifier
referenced in the dashboard and alert files. A referenced name that is not in
the rendered exposition is an error.

Deliberately out of scope: PromQL built-ins (``rate``, ``day_of_month``),
Prometheus-provided series (``up``, ``node_filesystem_*``), ``_bucket``/
``_count``/``_sum`` derivations (those are in the exposition), and any
third-party exporter series. Only ``bgpt_*`` names -- the ones this codebase
owns -- are graded, because those are the ones a code change can strand.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
DASHBOARD_DIR = REPO / "deploy" / "grafana" / "dashboards"
ALERT_FILE = REPO / "deploy" / "prometheus" / "alerts.yml"
#: Application-owned metric prefix. Everything else belongs to Prometheus or a
#: third-party exporter and cannot be validated from this repository.
OWNED_PREFIX = "bgpt_"
NAME_RE = re.compile(r"\bbgpt_[a-z0-9_]+\b")


def exported_sample_names() -> set[str]:
    """Names a dashboard may legitimately query from the app's exposition.

    Built from BOTH halves of the exposition, because a freshly started
    process exports ``# TYPE`` declarations for every metric but samples only
    for the ones it has already observed. Reading samples alone would call
    ``bgpt_ai_cost_usd_total`` unknown on a server that has not spent a token
    yet; reading declarations alone would miss the ``_bucket``/``_sum``
    derivations PromQL uses.
    """
    from prometheus_client import generate_latest

    from bangla_gpt_api.metrics import REGISTRY

    names: set[str] = set()
    families: dict[str, str] = {}
    for line in generate_latest(REGISTRY).decode("utf-8").splitlines():
        if not line:
            continue
        if line.startswith("# TYPE "):
            _, _, rest = line.partition("# TYPE ")
            family, _, metric_type = rest.partition(" ")
            families[family] = metric_type.strip()
            names.add(family)
            continue
        if line.startswith("#"):
            continue
        names.add(line.split("{", 1)[0].split(" ", 1)[0].strip())

    for family, metric_type in families.items():
        names.add(family)
        if metric_type in ("histogram", "summary"):
            names.update({f"{family}_bucket", f"{family}_count", f"{family}_sum"})
    return names


def dashboard_exprs() -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for path in sorted(DASHBOARD_DIR.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for panel in payload.get("panels", []):
            for target in panel.get("targets", []):
                expr = target.get("expr")
                if isinstance(expr, str):
                    found.append((path.name, expr))
    return found


def alert_exprs() -> list[tuple[str, str]]:
    """Alert expressions, read with the stdlib only (``expr: >`` blocks)."""
    if not ALERT_FILE.exists():
        return []
    found: list[tuple[str, str]] = []
    current: list[str] = []
    for raw in ALERT_FILE.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if stripped.startswith("expr:"):
            current = [stripped[len("expr:") :].strip()]
        elif current:
            if stripped.startswith(("- alert:", "labels:", "for:", "annotations:")) or not stripped:
                found.append((ALERT_FILE.name, " ".join(current)))
                current = []
            else:
                current.append(stripped)
    if current:
        found.append((ALERT_FILE.name, " ".join(current)))
    return found


def main() -> int:
    exported = exported_sample_names()
    problems: list[tuple[str, str, str]] = []
    checked = 0
    for source, expr in dashboard_exprs() + alert_exprs():
        for name in sorted(set(NAME_RE.findall(expr))):
            checked += 1
            if name not in exported:
                problems.append((source, name, expr))

    if not problems:
        print(
            f"all {checked} bgpt_* metric references across dashboards and alerts "
            f"are exported ({len(exported)} sample names in the registry)"
        )
        return 0

    for source, name, expr in sorted(set(problems)):
        print(f"::error file=deploy/**/{source}::{name} is not exported by metrics.py")
        print(f"    expr: {expr[:200]}")
    print(f"{len(problems)} unknown metric reference(s)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
