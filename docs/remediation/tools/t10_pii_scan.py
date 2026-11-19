"""T-10 step 3: personal-data scan over tracked data/fixture files.

Scans tracked .sql/.csv/.json/.txt/.py/.ts files that look like data
(dumps, seeds, fixtures) for: email addresses, Bangladeshi mobile numbers
(+8801[3-9]XXXXXXXX or 01[3-9]XXXXXXXX), NID-shaped digit runs (10/13/17
digits). Prints path + count only — never the matched value (H-15).
Test files are included because fixtures are exactly where fake PII
concentrates; counts feed the triage decision, not a leak report.
"""
from __future__ import annotations

import json
import re
import subprocess
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
BD_MOBILE = re.compile(r"(?:\+?880|0)1[3-9]\d{8}")
NID_SHAPE = re.compile(r"(?<!\d)(?:\d{17}|\d{13}|10\d{8})(?!\d)")

EXTS = {".sql", ".csv", ".json", ".jsonl", ".txt", ".md", ".py", ".ts", ".tsx"}
SKIP_PARTS = {"node_modules", ".git", "docs/remediation", ".venv", "dist", "coverage"}

files = [
    f
    for f in subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    if Path(f).suffix.lower() in EXTS
    and not any(part in f for part in SKIP_PARTS)
]

hits: Counter = Counter()
for rel in files:
    p = ROOT / rel
    try:
        text = p.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        continue
    e = len(EMAIL.findall(text))
    m = len(BD_MOBILE.findall(text))
    # NID-shaped runs are noisy in code (timestamps, hashes); only count them
    # in obvious data files so the number stays meaningful.
    n = len(NID_SHAPE.findall(text)) if p.suffix.lower() in {".sql", ".csv", ".json", ".jsonl"} else 0
    if e or m or n:
        hits[f"{rel} (email={e} mobile={m} nid_shape={n})"] += 1

print(f"scanned {len(files)} tracked data/fixture files")
print(f"files with personal-data-shaped hits: {len(hits)}")
for key in sorted(hits):
    print(f"  {key}")
