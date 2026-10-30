"""i18n guardrails: bn/en key parity, placeholder parity, English leaking into bn.

Run from CI so the defects found during the 2026-10-09 audit cannot come back:

    python scripts/check_i18n.py            # exits non-zero on violation
    python scripts/check_i18n.py --report   # print findings, always exit 0

Parity is already enforced at compile time by
`const en: Dict = Record<keyof typeof bn, string>` in apps/web/src/i18n.ts.
This script is the runtime backstop and adds what TypeScript cannot:

* placeholder parity, and Bangla values that contain no Bengali at all;
* the glossary's banned variants and register policy (`docs/glossary-bn.md`);
* counted English nouns without a singular form in `EN_SINGULAR`.

The dictionary is parsed as key/value pairs, including values the formatter
wrapped over several lines: the first version of this parser matched one line
per entry, so every wrapped value (a growing share of the dictionary) was
silently skipped by all checks.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

I18N = Path(__file__).resolve().parents[1] / "apps" / "web" / "src" / "i18n.ts"

KEY = re.compile(
    r'^\s{2}([A-Za-z_][A-Za-z0-9_]*):\s*("(?:[^"\\]|\\.)*")\s*,?\s*$',
    re.MULTILINE | re.DOTALL,
)
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

# Banned variant -> canonical term, from docs/glossary-bn.md. A value that
# reintroduces a retired variant fails here rather than on a reviewer's desk.
# Only the exact retired forms are banned: নম্বর stays for marks on a paper,
# উৎস stays for a content version's origin, মুছে ফেলা হয়েছে stays as a state.
BANNED_VARIANTS: dict[str, str] = {
    "লেসন প্ল্যান": "পাঠ পরিকল্পনা",
    "হোমওয়ার্ক": "বাড়ির কাজ",
    "রিভিশন": "পুনরালোচনা",
    "স্ট্রিক": "ধারাবাহিকতা",
    "সেভ করা": "সংরক্ষিত",
    "সেভ হয়েছে": "সংরক্ষিত হয়েছে",
    "মুছে ফেলুন": "মুছুন",
    "উৎস থেকে": "সূত্র থেকে",
    "সহায়তা প্ল্যান": "সহায়তা পরিকল্পনা",
    "স্টাডি মেটেরিয়াল": "পাঠসহায়ক উপকরণ",
    "সাশ্রয়ী সময়": "সাশ্রয় হওয়া সময়",
    "পরিসংখ্যা": "পরিসংখ্যান",
    "উদ্বেগজনক": "দুশ্চিন্তার",
    "সহায়তা যাচাই": "সহায়তা সেশনে প্রবেশ করুন",
    "গড় নম্বর": "গড় স্কোর",
}

#: Keys whose Bangla value may address the learner informally. The glossary's
#: register policy allows তুমি only where the string is the learner's own
#: words (tutor chips) or the AI persona's own question in an answer body.
INFORMAL_VOICE_KEYS = {
    "suggestTeach",
    "suggestSolve",
    "suggestQuizMe",
    "suggestImage",
    "imgSolve",
    "imgExplain",
    "imgCheck",
    "imgSteps",
    "saCheck",
}
INFORMAL_MARKER = re.compile("তুমি|তোমার|তোমাকে|তোমরা")

#: A counted English noun: a numeric placeholder, up to two modifier words,
#: then a plural noun. `heatmapSummary` is deliberately count-agnostic
#: (label:value pairs) and does not match.
COUNTED_NOUN = re.compile(
    r"\{(?:n|count|focus|days|questions|active|done|total|got|want)\}"
    r"(?:\s+\w+){0,2}\s+(questions|quizzes|students|minutes|days|sources|points|"
    r"attempts|chapters|classes)\b",
    re.IGNORECASE,
)


def parse(block: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in KEY.finditer(block):
        k, v = m.group(1), m.group(2)
        # Wrapped values arrive with the formatter's newline and indentation;
        # collapse to the single line a user actually reads.
        out[k] = " ".join(v[1:-1].split())
    return out


def dict_block(src: str, opener: str, closer: str | None) -> str:
    """The text of one dictionary literal, from its opening line.

    `en` used to be read as "everything from `const en` to the end of the
    file". Anything a later commit added below it -- a helper, a lookup map --
    was then parsed as translations, so a role map with two-space-indented
    entries (`student: "roleStudent",`) reported five keys as "present in en
    but missing from bn". That failure names the wrong cause and buries the
    real one, so the block now ends where the literal does.
    """
    start = src.index(opener)
    if closer is None:
        return src[start:]
    end = src.index(closer, start)
    return src[start : end + len(closer)]


def check_glossary(bn: dict[str, str]) -> list[str]:
    failures: list[str] = []
    for key, value in sorted(bn.items()):
        for banned, canonical in BANNED_VARIANTS.items():
            # The canonical term may contain the banned one as a prefix
            # (পরিসংখ্যান / পরিসংখ্যা); strip it before looking for the
            # retired form.
            if banned in value.replace(canonical, ""):
                failures.append(
                    f"glossary: {key!r} uses the retired variant {banned!r} "
                    f"-- use {canonical!r} (docs/glossary-bn.md)"
                )
        if key not in INFORMAL_VOICE_KEYS:
            marker = INFORMAL_MARKER.search(value)
            if marker:
                failures.append(
                    f"register: {key!r} addresses the user informally "
                    f"({marker.group(0)!r}); only the student-voice keys in "
                    "INFORMAL_VOICE_KEYS may (docs/glossary-bn.md)"
                )
    return failures


def check_english_plurals(en: dict[str, str], singular: dict[str, str]) -> list[str]:
    failures: list[str] = []
    for key, value in sorted(en.items()):
        if not COUNTED_NOUN.search(value):
            continue
        # A key may carry its singular as a sibling key instead of an
        # EN_SINGULAR entry (activityQuestions/activityQuestion predates the
        # table and its call sites select the form themselves).
        if key in singular or (key.endswith("s") and key[:-1] in en):
            continue
        failures.append(
            f"plural: {key!r} counts a plural noun but has no singular form "
            "(neither an EN_SINGULAR entry nor a sibling key); the en "
            f"sentence would read '...1 ...' at one: {value!r}"
        )
    for key, value in sorted(singular.items()):
        if key not in en:
            failures.append(f"plural: EN_SINGULAR names unknown key {key!r}")
            continue
        if value == en[key]:
            failures.append(f"plural: EN_SINGULAR[{key!r}] equals the plural sentence")
        if COUNTED_NOUN.search(value):
            failures.append(
                f"plural: EN_SINGULAR[{key!r}] still counts a plural noun: {value!r}"
            )
    return failures


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--report", action="store_true", help="print findings, always exit 0"
    )
    args = ap.parse_args()

    src = I18N.read_text(encoding="utf-8")
    try:
        bn = parse(dict_block(src, "const bn = {", "const en: Dict = {"))
        en = parse(dict_block(src, "const en: Dict = {", "\n};"))
        singular = parse(dict_block(src, "const EN_SINGULAR", "\n};"))
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

    glossary = check_glossary(bn)
    plural = check_english_plurals(en, singular)
    failures.extend(glossary)
    failures.extend(plural)

    print(f"i18n: {len(bn)} bn keys, {len(en)} en keys")
    print(f"  english-in-bn      : {len(leaks)}")
    print(
        f"  parity/placeholder : {len(failures) - len(leaks) - len(glossary) - len(plural)}"
    )
    print(f"  glossary/register  : {len(glossary)}")
    print(f"  plural             : {len(plural)}")

    if failures:
        print("\nFAILURES:")
        for f in failures:
            print(f"  - {f}")
        if args.report:
            return 0
        print(
            "\nA banned variant or an informal string in product voice is fixed in\n"
            "apps/web/src/i18n.ts, not here; a counted noun without a singular form\n"
            "gets one in EN_SINGULAR, next to the en dictionary."
        )
        return 1

    print("i18n guardrails OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
