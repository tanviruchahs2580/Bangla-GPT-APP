"""S6.2 content QA: automatic quality report + seeded human-sampling flow.

Sits on top of the extract -> bijoy -> normalize -> chunk pipeline. Where
``normalize.looks_like_garbage()`` gives a coarse per-page verdict, this
module gives per-chunk verdicts for the specific contract violations that
can survive ``normalize_bangla()`` and produce two artifacts:

1. An automatic quality report over a chunk JSONL file with a pass gate
   (fail = the corpus must not be indexed; a human investigates the
   flagged chunks listed in the report).
2. A seeded ~10% human-sampling flow: build a review sheet, a human
   records accept/reject verdicts, summarize rolls them up. Sampling is
   deterministic for a given seed so reviews are reproducible and the
   reject rate is an honest estimate over the sampled subset only.

Issue codes:
- ``not_nfc``:          text differs from its Unicode NFC normal form
- ``zero_width``:       ZWJ/ZWNJ/ZWSP/BOM survived normalization
- ``math_mojibake``:    UTF-8 math symbols misread as Latin-1 (double-encoded
                        multiplication, square-root, inequality, ellipsis)
- ``replacement_char``: U+FFFD present
- ``pua_char``:         private-use-area glyphs (custom-font residue)
- ``legacy_bijoy``:     unconverted Bijoy ASCII signatures present
"""

from __future__ import annotations

import random
import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from bangla_gpt_api.nctb.bijoy import is_likely_legacy_bijoy
from bangla_gpt_api.nctb.normalize import ZERO_WIDTH_CHARS

# Classic double-encoded math symbols: a multi-byte UTF-8 lead byte (C2/C3/E2)
# followed by a raw C1/Latin-1-supplement byte. Legitimate Bangla text
# never contains C1 control characters, so this pattern is safe.
_MATH_MOJIBAKE = re.compile("[\u00c2\u00c3\u00e2][\u0080-\u00bf]")

_PUA_RANGES = ((0xE000, 0xF8FF), (0xF0000, 0xFFFFD), (0x100000, 0x10FFFD))

ISSUE_CODES = (
    "not_nfc",
    "zero_width",
    "math_mojibake",
    "replacement_char",
    "pua_char",
    "legacy_bijoy",
)

# Default gate: index rebuilds are blocked when more than this fraction of
# chunks carries at least one QA issue.
DEFAULT_FLAGGED_THRESHOLD = 0.02


def _in_pua(char: str) -> bool:
    cp = ord(char)
    return any(lo <= cp <= hi for lo, hi in _PUA_RANGES)


def qa_text(text: str) -> list[str]:
    """Return the sorted list of QA issue codes found in one text."""
    issues: list[str] = []
    if unicodedata.normalize("NFC", text) != text:
        issues.append("not_nfc")
    if any(ch in text for ch in ZERO_WIDTH_CHARS):
        issues.append("zero_width")
    if _MATH_MOJIBAKE.search(text):
        issues.append("math_mojibake")
    if "\ufffd" in text:
        issues.append("replacement_char")
    if any(_in_pua(ch) for ch in text):
        issues.append("pua_char")
    if is_likely_legacy_bijoy(text):
        issues.append("legacy_bijoy")
    return sorted(issues)


@dataclass
class ChunkQAReport:
    total_chunks: int
    flagged_chunks: int
    flagged_ratio: float
    issues: dict[str, int] = field(default_factory=dict)
    worst: list[dict] = field(default_factory=list)
    passed: bool = False
    threshold: float = DEFAULT_FLAGGED_THRESHOLD

    def to_dict(self) -> dict:
        return {
            "total_chunks": self.total_chunks,
            "flagged_chunks": self.flagged_chunks,
            "flagged_ratio": self.flagged_ratio,
            "issues": self.issues,
            "worst": self.worst,
            "pass": self.passed,
            "threshold": self.threshold,
        }


def qa_chunks(
    chunks: Iterable[Mapping[str, object]],
    *,
    threshold: float = DEFAULT_FLAGGED_THRESHOLD,
    worst_limit: int = 20,
) -> ChunkQAReport:
    """Run QA over chunk mappings (needs ``chunk_id`` and ``text`` keys)."""
    total = 0
    flagged = 0
    counts: dict[str, int] = {code: 0 for code in ISSUE_CODES}
    worst: list[dict] = []
    for chunk in chunks:
        chunk_id = str(chunk.get("chunk_id", ""))
        text = str(chunk.get("text", ""))
        total += 1
        issues = qa_text(text)
        if not issues:
            continue
        flagged += 1
        for code in issues:
            counts[code] = counts.get(code, 0) + 1
        if len(worst) < worst_limit:
            worst.append({"chunk_id": chunk_id, "issues": issues})
    ratio = (flagged / total) if total else 1.0
    passed = total > 0 and ratio <= threshold
    return ChunkQAReport(
        total_chunks=total,
        flagged_chunks=flagged,
        flagged_ratio=round(ratio, 4),
        issues={code: n for code, n in counts.items() if n},
        worst=worst,
        passed=passed,
        threshold=threshold,
    )


def build_review_sheet(
    chunks: list[Mapping[str, object]],
    *,
    seed: int,
    fraction: float = 0.10,
    excerpt_chars: int = 400,
) -> list[dict]:
    """Deterministic ~``fraction`` human-sampling sheet for one corpus."""
    rng = random.Random(seed)  # noqa: S311 - sampling, not security
    if not chunks:
        return []
    k = max(1, round(len(chunks) * fraction))
    chosen = rng.sample(chunks, k)
    sheet: list[dict] = []
    for chunk in sorted(chosen, key=lambda c: str(c.get("chunk_id", ""))):
        text = str(chunk.get("text", ""))
        sheet.append(
            {
                "chunk_id": str(chunk.get("chunk_id", "")),
                "chapter": str(chunk.get("chapter", "")),
                "excerpt": text[:excerpt_chars],
                "qa_issues": qa_text(text),
                "verdict": "",
                "note": "",
            }
        )
    return sheet


def summarize_review(sheet: list[dict], verdicts: list[dict]) -> dict:
    """Roll human verdicts (``{chunk_id, verdict}``) up against a sheet."""
    wanted = {row["chunk_id"] for row in sheet}
    by_id = {str(v.get("chunk_id", "")): str(v.get("verdict", "")) for v in verdicts}
    reviewed_ids = wanted & set(by_id)
    accepted = sum(1 for cid in reviewed_ids if by_id[cid] == "accept")
    rejected = sum(1 for cid in reviewed_ids if by_id[cid] == "reject")
    reviewed = len(reviewed_ids)
    return {
        "sampled": len(sheet),
        "reviewed": reviewed,
        "pending": len(sheet) - reviewed,
        "accepted": accepted,
        "rejected": rejected,
        "reject_ratio": round(rejected / reviewed, 4) if reviewed else 0.0,
        "complete": reviewed == len(sheet) and len(sheet) > 0,
    }


__all__ = [
    "DEFAULT_FLAGGED_THRESHOLD",
    "ISSUE_CODES",
    "ChunkQAReport",
    "build_review_sheet",
    "qa_chunks",
    "qa_text",
    "summarize_review",
]
