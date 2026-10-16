"""i18n guardrails: bn/en key parity, placeholder parity, English leaking into bn.

Run from CI so the defects found during the 2026-10-09 audit cannot come back:

    python scripts/check_i18n.py            # exits non-zero on violation
    python scripts/check_i18n.py --report   # print findings, always exit 0

Parity is already enforced at compile time by
`const en: Dict = Record<keyof typeof bn, string>` in apps/web/src/i18n.ts.
This script is the runtime backstop and adds two checks TypeScript cannot:
placeholder parity, and Bangla values that contain no Bengali at all.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

I18N = Path(__file__).resolve().parents[1] / "apps" / "web" / "src" / "i18n.ts"

KEY = re.compile(r"^\s{2}([A-Za-z_][A-Za-z0-9_]*):\s*(.*?),?\s*$", re.MULTILINE)
BENGALI = re.compile(r"[\u0980-\u09FF]")
LATIN_WORD = re.compile(r"[A-Za-z]{3,}")
PLACEHOLDER = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")

# Values allowed to contain no Bengali.
#
# PERMANENT: genuine brand names that stay as-is in both dictionaries.
ACRONYM_ALLOWLIST = {
    "appName",  # product name, transliterated deliberately
}

# EMPTY, and it should stay that way. This set existed for keys whose Bangla
# copy was owed by a native speaker (audit 2026-10-09, AUD-0047). The
# 2026-10-16 pass landed reviewed Bangla for all eight -- the status-page
# headings, the status detail lines and the impersonation banner strings that
# SEC-08 requires to be visibly bannered -- so nothing is pending.
#
# Do NOT add to this list to silence a new finding: it exists to make owed
# copy visible, and every entry costs that visibility.
PENDING_BANGLA_REVIEW: set[str] = set()


def parse(block: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in KEY.finditer(block):
        k, v = m.group(1), m.group(2).strip().rstrip(",").strip()
        if len(v) >= 2 and v[0] in "\"'" and v[-1] == v[0]:
            out[k] = v[1:-1]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--report", action="store_true", help="print findings, always exit 0"
    )
    args = ap.parse_args()

    src = I18N.read_text(encoding="utf-8")
    try:
        bn = parse(src[src.index("const bn = {") : src.index("const en: Dict = {")])
        en = parse(src[src.index("const en: Dict = {") :])
    except ValueError as exc:  # pragma: no cover - structural change in i18n.ts
        print(f"check_i18n: cannot locate the bn/en dictionaries in {I18N}: {exc}")
        return 2

    failures: list[str] = []

    for k in sorted(set(bn) - set(en)):
        failures.append(f"key parity: {k!r} present in bn but missing from en")
    for k in sorted(set(en) - set(bn)):
        failures.append(f"key parity: {k!r} present in en but missing from bn")

    for k in sorted(set(bn) & set(en)):
        pb, pe = set(PLACEHOLDER.findall(bn[k])), set(PLACEHOLDER.findall(en[k]))
        if pb != pe:
            failures.append(
                f"placeholder parity: {k!r} bn={sorted(pb)} en={sorted(pe)}"
            )

    leaks = []
    for k, v in bn.items():
        if k in ACRONYM_ALLOWLIST or BENGALI.search(v):
            continue
        if len(LATIN_WORD.findall(v)) < 2:
            continue
        if k in PENDING_BANGLA_REVIEW:
            print(f"  pending Bangla copy (AUD-0047): {k}")
            continue
        leaks.append(f"english-in-bn: {k!r} = {v!r} (no Bengali character)")
    failures.extend(leaks)

    stale = sorted(PENDING_BANGLA_REVIEW - set(bn))
    for k in stale:
        failures.append(
            f"stale exception: {k!r} is in PENDING_BANGLA_REVIEW but no longer exists in i18n.ts -- "
            "if its Bangla copy has landed, delete it from the list"
        )

    print(f"i18n: {len(bn)} bn keys, {len(en)} en keys")
    print(f"  english-in-bn      : {len(leaks)}")
    print(f"  parity/placeholder : {len(failures) - len(leaks)}")

    if failures:
        print("\nFAILURES:")
        for f in failures:
            print(f"  - {f}")
        if args.report:
            return 0
        print(
            "\nIf an English value in bn is a deliberate product decision, add its key to\n"
            "ACRONYM_ALLOWLIST with a comment, rather than deleting the check."
        )
        return 1

    print("i18n guardrails OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
