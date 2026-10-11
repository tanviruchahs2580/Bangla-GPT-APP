"""AUD-0013: the README endpoint table must not contradict the app's own gates.

The finding was that README listed `GET /metrics` as unauthenticated while
main.py refuses to start in production unless METRICS_REQUIRE_AUTH is true and
METRICS_TOKEN is set. Rather than hand-maintain the table forever, this script
re-derives the facts it depends on and fails when the README drifts.
"""

import re
import sys
from pathlib import Path


def _repo_root() -> Path:
    """Walk up to the directory that actually looks like the repository root.

    Depth arithmetic breaks the moment the script moves, so anchor on content
    the repository certainly has instead.
    """
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "README.md").is_file() and (candidate / "Dockerfile").is_file():
            return candidate
    raise SystemExit(f"could not locate the repository root from {__file__}")


REPO = _repo_root()
README = REPO / "README.md"

text = README.read_text(encoding="utf-8")
problems: list[str] = []

# 1. The metrics row must not claim "no auth" any more.
metrics_row = next(
    (line for line in text.splitlines() if line.startswith("| `GET /metrics`")), None
)
if metrics_row is None:
    problems.append("README has no `GET /metrics` row to check")
elif "env-dependent" not in metrics_row:
    problems.append(
        "README `GET /metrics` row must say auth is environment-dependent; got: "
        + metrics_row.strip()
    )

# 2. The footnote the row points at must exist and name the real variables.
if "METRICS_REQUIRE_AUTH" not in text:
    problems.append(
        "README does not explain METRICS_REQUIRE_AUTH; a reader cannot tell when "
        "/metrics is protected"
    )
if "METRICS_TOKEN" not in text:
    problems.append("README does not mention METRICS_TOKEN")

# 3. The claim must match the code: production refuses to boot without both.
main_py = (REPO / "apps" / "api" / "src" / "bangla_gpt_api" / "main.py").read_text(encoding="utf-8")
gate = re.search(r"def _validate_metrics.*?\n(?=\ndef )", main_py, re.S)
if gate is None:
    problems.append("_validate_metrics not found in main.py - README claim unverifiable")
else:
    body = gate.group(0)
    for needed in ("metrics_require_auth", "metrics_token"):
        if needed not in body:
            problems.append(
                f"main.py's _validate_metrics no longer checks {needed}; update the README note"
            )

# 4. The settings the README implies must still exist in Settings.
settings_src = (REPO / "apps" / "api" / "src" / "bangla_gpt_api" / "config.py").read_text(
    encoding="utf-8"
)
for field in ("metrics_require_auth", "metrics_token"):
    if field not in settings_src:
        problems.append(f"Settings no longer declares {field}; README is stale")

# 5. The npm command the README tells developers to run must match CI.
if "npm install" in text and "npm ci" not in text:
    problems.append(
        "README tells developers to run `npm install` while CI uses `npm ci`; "
        "use `npm ci` so local and CI installs agree"
    )

# 6. DOC-05: docs/ claims exactly one current QA record; make that true rather
#    than aspirational. Superseded reports belong in docs/archive/.
qa_records = [
    p
    for p in (REPO / "docs").glob("*.md")
    if "qa" in p.name.lower() or "certification" in p.name.lower()
]
if len(qa_records) != 1:
    problems.append(
        f"docs/ must hold exactly one current QA record, found {len(qa_records)}: "
        f"{sorted(p.name for p in qa_records)}"
    )

# 7. Every relative link in the README must resolve. A dead link in the front
#    page is the most expensive kind of documentation rot.
for match in re.finditer(r"\]\(([^)#][^)]*)\)", text):
    link = match.group(1).split("#", 1)[0]
    if link.startswith(("http://", "https://", "mailto:")):
        continue
    # Path separators in the README are always "/". On Windows that string also
    # works as a separator, but on POSIX a backslash is an ordinary character,
    # so a "docs\file.md" target never resolved and every link looked dead.
    # Joining the POSIX-style segments lets pathlib use the native separator.
    target = REPO.joinpath(*link.split("/"))
    if not target.exists():
        problems.append(f"README links to a path that does not exist: {link}")

for problem in problems:
    print("::error::" + problem)

if problems:
    sys.exit(1)

print("README endpoint table agrees with the metrics gate and CI install command.")
