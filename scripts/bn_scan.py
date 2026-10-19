#!/usr/bin/env python3
"""bn_scan.py - read-only Bangla text hygiene scanner.

Copied verbatim from Appendix C.3 of the audit prompt. Lives in the sandbox
(OUTPUT_DIR), NOT in the repository.

Usage (Windows):
  git ls-files | python bn_scan.py --list-from-stdin
Every hit is a CANDIDATE for review. Never auto-fix prose from this output (AH-21).
"""

import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

TEXT_EXT = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".json",
    ".md",
    ".txt",
    ".html",
    ".css",
    ".yml",
    ".yaml",
    ".toml",
    ".csv",
    ".sql",
    ".po",
    ".ini",
    ".cfg",
    ".svg",
}
MAX_BYTES = 5_000_000
BN = "\u0980-\u09ff"  # Bengali block
ZW = "\u200c\u200d"  # ZWNJ, ZWJ
TOKEN = f"[A-Za-z0-9{BN}{ZW}]"

CHECKS = {
    "ASSAMESE_LETTER": re.compile("[\u09f0\u09f1]"),
    "DEVANAGARI_NON_PUNCT": re.compile("[\u0900-\u0963\u0966-\u097f]"),
    "RARE_BENGALI_SIGN": re.compile("[\u0980\u09f2\u09f4-\u09fe]"),
    "ZWJ_ZWNJ_REVIEW": re.compile(f"[{ZW}]"),
    "VOWEL_SIGN_AT_TOKEN_START": re.compile(f"(?<![{BN}{ZW}])[\u09be-\u09cc\u09d7]"),
    "HASANTA_NOT_BEFORE_LETTER": re.compile(f"\u09cd(?![{BN}{ZW}])"),
    "MIXED_SCRIPT_TOKEN": re.compile(f"(?={TOKEN}*[A-Za-z])(?={TOKEN}*[{BN}]){TOKEN}+"),
    "PIPE_USED_AS_DANDA": re.compile(f"(?<=[{BN}])\\s*\\|(?=\\s|$)"),
    "REPLACEMENT_CHAR": re.compile("\ufffd"),
    "BOM_INSIDE_TEXT": re.compile("\ufeff"),
}


#: Reviewed fixtures: files whose whole purpose is to CONTAIN the character the
#: check looks for, or generated artifacts whose encoding is deliberate. Same
#: pattern as scripts/check_placeholders.py's ALLOW: an explicit path, the
#: check it is exempt from, and the reason. Anything not listed here still
#: fails the gate.
EXEMPT: tuple[tuple[str, str, str], ...] = (
    (
        "apps/api/tests/test_eval2_generation.py",
        "ASSAMESE_LETTER",
        "the mis-script detector's own test: U+09F0 must appear here for "
        "mis_script() to have something to detect",
    ),
    (
        "apps/api/tests/test_rag2_cache_scope.py",
        "DEVANAGARI_NON_PUNCT",
        "the cache-key test asserts a Devanagari query does not collide with "
        "the Bengali one, so the input must be Devanagari",
    ),
    (
        "apps/api/eval/review_sheets/synthetic_review_sheet.csv",
        "BOM_INSIDE_TEXT",
        "generated review sheet written UTF-8-BOM so Excel opens Bengali "
        "correctly; the BOM is the compatibility marker, not stray text",
    ),
    (
        "apps/api/eval/review_sheets/class_appropriateness_sheet.csv",
        "BOM_INSIDE_TEXT",
        "same exporter, same Excel reason",
    ),
    (
        "apps/api/eval/review_sheets/synthetic_review_sheet.csv",
        "NOT_NFC",
        "the source text is quoted from the corpus verbatim (A2-03 keeps the "
        "corpus form; normalisation happens at ingest), so the sheet carries "
        "the corpus's own sequence",
    ),
)


def _exempt(path: Path, check: str) -> bool:
    as_posix = path.as_posix()
    return any(
        as_posix.endswith(allowed) and check == for_check for allowed, for_check, _ in EXEMPT
    )


def scan(path: Path, totals: Counter) -> None:
    if path.suffix.lower() not in TEXT_EXT or not path.is_file():
        return
    size = path.stat().st_size
    if size > MAX_BYTES:
        print(f"SKIPPED_LARGE {path} ({size} bytes): review with a streaming scan")
        return
    text = path.read_text(encoding="utf-8", errors="replace")
    for lineno, line in enumerate(text.splitlines(), 1):
        if unicodedata.normalize("NFC", line) != line and not _exempt(path, "NOT_NFC"):
            totals["NOT_NFC"] += 1
            print(f"{path}:{lineno}  NOT_NFC")
        for name, rx in CHECKS.items():
            if _exempt(path, name):
                continue
            for m in rx.finditer(line):
                totals[name] += 1
                label = ""
                if name != "MIXED_SCRIPT_TOKEN":
                    ch = m.group(0).strip()[-1:] or m.group(0)[-1:]
                    label = f"U+{ord(ch):04X} {unicodedata.name(ch, 'UNNAMED')}"
                ctx = line[max(0, m.start() - 12) : m.end() + 12]
                print(f"{path}:{lineno}:{m.start() + 1}  {name}  {label}  | {ctx}")


def main(paths: list[str]) -> None:
    totals: Counter = Counter()
    for raw in paths:
        scan(Path(raw), totals)
    print("\nSUMMARY (candidates, not findings)")
    for name in [*CHECKS, "NOT_NFC"]:
        print(f"{name:28} {totals[name]}")


if __name__ == "__main__":
    if sys.argv[1:2] == ["--list-from-stdin"]:
        main([l.strip() for l in sys.stdin if l.strip()])
    else:
        main(sys.argv[1:])
