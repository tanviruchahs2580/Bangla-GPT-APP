"""DORA-style delivery metrics from the repository's own history (AUD-EF-14 / F-17).

The audit computed these numbers by hand from `git log` and `gh run list` and
nothing in the tree tracked them. This script derives them where the data
exists and says BLOCKED where it does not -- it never fills a gap with an
estimate.

Metrics (DORA 2024 definitions, adapted to what this repository records):

* **Deployment frequency** -- release tags (``v*.*.*``) per week over the
  window. A tag is the deployable event this repository has; pushes to ``main``
  are counted separately because ``main`` is continuously integrated, not
  continuously deployed.
* **Lead time for changes** -- for each release tag: the time from the oldest
  commit first introduced by the merge that brought the change to the tag, and
  for merge commits the timespan from the branch's oldest new commit to the
  merge itself. Median and p90 are reported; the merge-commit view is what a
  reviewer actually waits for.
* **Change failure rate** -- the share of completed ``API CI`` runs on ``main``
  that concluded ``failure`` (cancelled runs are excluded: a superseded run is
  not a failure).
* **Recovery time** -- median time from a failed ``API CI`` run on ``main`` to
  the next successful one.

Usage:

    python scripts/dora_report.py                     # last 90 days, markdown
    python scripts/dora_report.py --days 180 --json .audit/tmp/dora.json

Requirements: ``git`` (always) and an authenticated ``gh`` for the CI metrics;
without ``gh`` the git metrics still print and the CI ones are marked BLOCKED.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = "ci.yml"


def run(cmd: list[str], cwd: Path = ROOT) -> str | None:
    try:
        out = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return out.stdout


def git_ts(*args: str) -> list[dt.datetime]:
    """Return commit/ref timestamps for a git command printing %cI (ISO 8601)."""
    out = run(["git", *args])
    if out is None:
        return []
    stamps = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            stamps.append(dt.datetime.fromisoformat(line))
        except ValueError:
            continue
    return stamps


def deployment_frequency(since: dt.datetime) -> dict:
    out = run(
        [
            "git",
            "for-each-ref",
            "--sort=creatordate",
            "--format=%(refname:short)\t%(creatordate:iso-strict)",
            "refs/tags/",
        ]
    )
    tags = []
    for line in (out or "").splitlines():
        if "\t" not in line:
            continue
        name, created = line.split("\t", 1)
        if not name.startswith("v"):
            continue
        try:
            stamp = dt.datetime.fromisoformat(created)
        except ValueError:
            continue
        if stamp >= since:
            tags.append({"tag": name, "created": stamp.isoformat()})
    weeks = max((dt.datetime.now(dt.timezone.utc) - since).days / 7.0, 1 / 7.0)
    main_pushes = git_ts("log", "--first-parent", "--since", since.isoformat(), "--format=%cI", "HEAD")
    return {
        "window_days": (dt.datetime.now(dt.timezone.utc) - since).days,
        "release_tags": tags,
        "release_tags_per_week": round(len(tags) / weeks, 2),
        "main_commits": len(main_pushes),
        "main_commits_per_week": round(len(main_pushes) / weeks, 2),
    }


def merge_lead_times(limit: int) -> list[float]:
    """Hours from a merge's oldest new branch commit to the merge itself."""
    out = run(
        [
            "git",
            "log",
            "--merges",
            "--first-parent",
            f"-{limit}",
            "--format=%H\t%cI",
        ]
    )
    lead_hours: list[float] = []
    for line in (out or "").splitlines():
        if "\t" not in line:
            continue
        sha, merged_at = line.split("\t", 1)
        try:
            merged = dt.datetime.fromisoformat(merged_at)
        except ValueError:
            continue
        # The merge's second parent is the branch tip; the branch's own commits
        # are everything reachable from it and not from the first parent.
        parents = run(["git", "rev-list", "--parents", "-n", "1", sha])
        if not parents:
            continue
        parts = parents.split()
        if len(parts) < 3:
            continue
        first_ts = git_ts("log", "--format=%cI", f"{parts[1]}..{parts[2]}")
        if not first_ts:
            continue
        oldest = min(first_ts)
        delta = (merged - oldest).total_seconds() / 3600.0
        if delta >= 0:
            lead_hours.append(delta)
    return lead_hours


def tag_lead_times() -> list[float]:
    """Hours from a tagged commit's author date to the tag's creation date."""
    tags = run(["git", "for-each-ref", "--format=%(refname:short)\t%(creatordate:iso-strict)", "refs/tags/"])
    lead: list[float] = []
    for line in (tags or "").splitlines():
        if "\t" not in line:
            continue
        name, created = line.split("\t", 1)
        if not name.startswith("v"):
            continue
        author = git_ts("log", "-1", "--format=%aI", f"{name}^{{commit}}")
        if not author:
            continue
        try:
            created_ts = dt.datetime.fromisoformat(created)
        except ValueError:
            continue
        delta = (created_ts - author[0]).total_seconds() / 3600.0
        if delta >= 0:
            lead.append(delta)
    return lead


def ci_runs(limit: int) -> list[dict] | None:
    if shutil.which("gh") is None:
        return None
    out = run(
        [
            "gh",
            "run",
            "list",
            "--workflow",
            WORKFLOW,
            "--branch",
            "main",
            "--limit",
            str(limit),
            "--json",
            "conclusion,status,createdAt,updatedAt,event,headSha",
        ]
    )
    if out is None:
        return None
    try:
        runs = json.loads(out)
    except json.JSONDecodeError:
        return None
    runs.sort(key=lambda r: r.get("createdAt", ""))
    return runs


def change_failure_and_recovery(runs: list[dict] | None) -> dict:
    if runs is None:
        return {
            "status": "BLOCKED",
            "reason": "gh is unavailable or unauthenticated; the CI run history cannot be read here",
        }
    completed = [r for r in runs if r.get("status") == "completed"]
    executed = [r for r in completed if r.get("conclusion") != "cancelled"]
    failures = [r for r in executed if r.get("conclusion") == "failure"]
    recoveries: list[float] = []
    for index, run_row in enumerate(executed):
        if run_row.get("conclusion") != "failure":
            continue
        for later in executed[index + 1 :]:
            if later.get("conclusion") == "success":
                try:
                    failed_at = dt.datetime.fromisoformat(run_row["updatedAt"].replace("Z", "+00:00"))
                    fixed_at = dt.datetime.fromisoformat(later["updatedAt"].replace("Z", "+00:00"))
                except (KeyError, ValueError):
                    break
                recoveries.append((fixed_at - failed_at).total_seconds() / 3600.0)
                break
    return {
        "status": "VERIFIED" if executed else "UNVERIFIED",
        "completed_runs": len(completed),
        "executed_runs_excluding_cancelled": len(executed),
        "failed_runs": len(failures),
        "change_failure_rate_pct": round(100.0 * len(failures) / len(executed), 1) if executed else None,
        "recovery_hours_median": round(statistics.median(recoveries), 1) if recoveries else None,
        "recovery_samples": len(recoveries),
    }


def summarise(values: list[float]) -> dict:
    if not values:
        return {"samples": 0}
    return {
        "samples": len(values),
        "median_hours": round(statistics.median(values), 1),
        "p90_hours": round(sorted(values)[max(int(0.9 * (len(values) - 1)), 0)], 1),
        "max_hours": round(max(values), 1),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=90, help="window for frequency metrics (default 90)")
    parser.add_argument("--limit", type=int, default=100, help="CI runs to read (default 100)")
    parser.add_argument("--json", default=None, help="also write the report as JSON to this path")
    args = parser.parse_args(argv)

    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.days)
    report = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "repository": str(ROOT),
        "head": (run(["git", "rev-parse", "HEAD"]) or "unknown").strip(),
        "window_days": args.days,
        "deployment_frequency": deployment_frequency(since),
        "lead_time_tag_hours": summarise(tag_lead_times()),
        "lead_time_merge_hours": summarise(merge_lead_times(args.limit)),
        "ci": change_failure_and_recovery(ci_runs(args.limit)),
    }

    freq = report["deployment_frequency"]
    print("## DORA-style delivery metrics")
    print()
    print(f"Window: last {freq['window_days']} days -- HEAD {report['head'][:12]}")
    print()
    print("| Metric | Value | Basis |")
    print("| --- | --- | --- |")
    print(
        f"| Deployment frequency | {freq['release_tags_per_week']} release tags/week "
        f"({len(freq['release_tags'])} tags in window) | `git for-each-ref refs/tags` |"
    )
    print(
        f"| Integration frequency | {freq['main_commits_per_week']} commits/week to main "
        f"({freq['main_commits']} commits) | `git log --first-parent` |"
    )
    lead_tag = report["lead_time_tag_hours"]
    print(
        "| Lead time (commit to tag) | "
        + (f"{lead_tag['median_hours']} h median, p90 {lead_tag['p90_hours']} h, n={lead_tag['samples']}" if lead_tag["samples"] else "no release tags yet")
        + " | `git log -1 --format=%aI` per tag |"
    )
    lead_merge = report["lead_time_merge_hours"]
    print(
        "| Lead time (branch to merge) | "
        + (f"{lead_merge['median_hours']} h median, p90 {lead_merge['p90_hours']} h, n={lead_merge['samples']}" if lead_merge["samples"] else "no merge commits")
        + " | newest branch commit to merge commit |"
    )
    ci = report["ci"]
    if ci["status"] == "BLOCKED":
        print(f"| Change failure rate | BLOCKED -- {ci['reason']} | `gh run list --workflow {WORKFLOW}` |")
        print("| Recovery time | BLOCKED -- same cause | consecutive main runs |")
    else:
        cfr = ci["change_failure_rate_pct"]
        mttr = ci["recovery_hours_median"]
        print(
            f"| Change failure rate | {cfr}% ({ci['failed_runs']}/{ci['executed_runs_excluding_cancelled']} executed runs on main) | `gh run list --workflow {WORKFLOW} --branch main` |"
        )
        print(
            f"| Recovery time | "
            + (f"{mttr} h median (n={ci['recovery_samples']})" if mttr is not None else "no failure-recovery pairs in the window")
            + " | failed run to next successful run |"
        )
    print()
    print("Cancelled runs are excluded from the failure rate: a superseded run is not a failure.")
    print("Data sources: git tags and history; GitHub Actions runs API where `gh` is authenticated.")

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        print(f"JSON written to {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
