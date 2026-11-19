"""T-01 Batch A: command-driven verification of leads F-01/08/09/10/11/15/21/30.

Stdlib-only, UTF-8, run from the repository root. Prints one section per lead
with the raw counts the finding rows cite. No secrets, no personal data.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
API = ROOT / "apps" / "api"
WEB = ROOT / "apps" / "web"
SHA = subprocess.run(
    ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
).stdout.strip()
print(f"HEAD {SHA}")


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout


# --- F-01 supplement: SQLite/log files ever added to history -----------------
print("== F-01 history .db/.log ==")
names = git("log", "--all", "--diff-filter=A", "--name-only", "--format=")
dbhits = sorted(
    {n for n in names.splitlines() if re.search(r"\.(db|sqlite3?|log)$", n, re.I) or re.search(r"\.db\.", n, re.I)}
)
for n in dbhits[:40]:
    print(f"history-tracked: {n}")
print(f"history .db/.log/.sqlite count: {len(dbhits)}")

# --- F-21: version declarations ---------------------------------------------
print("== F-21 version declarations ==")
patterns = ["0.15.0", '"version"']
pyproject = (API / "pyproject.toml").read_text(encoding="utf-8")
pkg = json.loads((WEB / "package.json").read_text(encoding="utf-8"))
cap = json.loads((WEB / "capacitor.config.ts").read_text(encoding="utf-8").split("=", 1)[1]) if False else None
print(f"apps/api/pyproject.toml project.version: {json.dumps(re.search(r'^version = \"([^\"]+)\"', pyproject, re.M).group(1))}")
print(f"apps/web/package.json version: {json.dumps(pkg.get('version'))}")
for rel in ("src/manifest.webmanifest", "public/manifest.webmanifest"):
    p = WEB / rel
    if p.exists():
        man = json.loads(p.read_text(encoding="utf-8"))
        print(f"apps/web/{rel} version: {json.dumps(man.get('version'))}")
src = git("grep", "-n", "-E", r"APP_VERSION|__version__|versionName|versionCode", "--", "apps")
for line in src.splitlines()[:25]:
    print(line)

# --- F-11: router LOC + async handlers with sync session ---------------------
print("== F-11 router LOC and async-with-Session ==")
routers = sorted((API / "src" / "bangla_gpt_api" / "routers").glob("*.py"))
total_loc = 0
for r in routers:
    loc = len(r.read_text(encoding="utf-8").splitlines())
    total_loc += loc
    print(f"{r.name}: {loc}")
print(f"routers total LOC: {total_loc}")
main_loc = len((API / "src" / "bangla_gpt_api" / "main.py").read_text(encoding="utf-8").splitlines())
print(f"main.py LOC: {main_loc}")
async_session = []
for r in routers:
    for i, line in enumerate(r.read_text(encoding="utf-8").splitlines(), 1):
        if re.search(r"async def .*Session", line):
            async_session.append(f"{r.name}:{i}: {line.strip()[:90]}")
print(f"async def handlers with Session param: {len(async_session)}")
for x in async_session[:15]:
    print(x)

# --- F-09: JSON columns holding ID lists -------------------------------------
print("== F-09 JSON columns in models ==")
models = (API / "src" / "bangla_gpt_api" / "db" / "models.py").read_text(encoding="utf-8")
for i, line in enumerate(models.splitlines(), 1):
    if "JSON" in line and "=" in line and ("Column" in line or "mapped_column" in line):
        print(f"models.py:{i}: {line.strip()[:120]}")

# --- F-10: FK ondelete enumeration -------------------------------------------
print("== F-10 FK ondelete ==")
ondelete = re.findall(r"ondelete=\"([A-Z]+)\"", models)
print(f"ForeignKey ondelete= occurrences: {len(ondelete)}")
fk_all = re.findall(r"ForeignKey\(", models)
print(f"ForeignKey( occurrences: {len(fk_all)}")

# --- F-15: frontend sizes / e2e ----------------------------------------------
print("== F-15 frontend ==")
for rel in ("src/i18n.ts", "src/lib/api.ts", "src/lib/apiClient.ts", "src/lib/http.ts"):
    p = WEB / rel
    if p.exists():
        print(f"{rel}: {len(p.read_text(encoding='utf-8').splitlines())} lines")
e2e = WEB / "e2e"
if e2e.is_dir():
    specs = sorted(p.name for p in e2e.glob("*.spec.ts"))
    print(f"e2e specs: {len(specs)} -> {specs}")
lang_switch = git("grep", "-n", "-E", "window.location|location.reload", "--", "apps/web/src")
reload_hits = [l for l in lang_switch.splitlines() if "reload" in l.lower()]
print(f"location.reload hits in web src: {len(reload_hits)}")
for l in reload_hits[:10]:
    print(l)

# --- F-08: eval counts / provenance -------------------------------------------
print("== F-08 eval data ==")
for rel in ("eval/golden_questions.json", "eval/golden_v3.json", "eval/redteam_v2.json", "eval/baseline_v3.json"):
    p = API / rel
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            items = data.get("items", data if isinstance(data, list) else [])
            print(f"{rel}: top-level keys={sorted(data.keys()) if isinstance(data, dict) else 'list'}; items={len(items)}")
        except Exception as exc:  # noqa: BLE001 - report-only tooling
            print(f"{rel}: parse error {type(exc).__name__}")
    else:
        print(f"{rel}: absent")
evaldir = sorted(p.name for p in (API / "eval").glob("*"))
print(f"eval dir entries: {evaldir}")

# --- F-30: routes outside OpenAPI ---------------------------------------------
print("== F-30 routes vs OpenAPI ==")
routes = json.loads((ROOT / "docs/remediation/evidence/T-00/routes.baseline.json").read_text(encoding="utf-8"))
top = routes["app_routes_top_level"]
not_in_schema = [t for t in top if t["type"] != "_IncludedRouter"]
print(f"top-level Route entries outside included routers: {[(t['name'], t['path']) for t in not_in_schema]}")
openapi = json.loads((ROOT / "docs/remediation/evidence/T-00/openapi.baseline.json").read_text(encoding="utf-8"))
ops_paths = set(openapi["paths"].keys())
served = routes["resolved_served_routes"]
outside = sorted(p for p in served if p not in ops_paths)
print(f"resolved served paths: {len(served)}; in OpenAPI: {len(served) - len(outside)}; outside: {outside}")

# --- F-17: git process ---------------------------------------------------------
print("== F-17 git process ==")
branches = git("branch", "-a").splitlines()
print(f"branches (local+remote refs): {len(branches)}")
log = git("log", "--oneline", "-15")
print(log)
rootdocs = [p.name for p in ROOT.glob("*.md")]
print(f"root-level .md files: {rootdocs}")
