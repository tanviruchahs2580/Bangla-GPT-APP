"""content QA: automatic quality report + seeded human-sampling flow.

Sits on top of the extract -> bijoy -> normalize -> chunk pipeline. Where
``normalize.looks_like_garbage`` gives a coarse per-page verdict, this
module gives per-chunk verdicts for the specific contract violations that
can survive ``normalize_bangla`` and produce two artifacts:

1. An automatic quality report over a chunk JSONL file with a pass gate
   (fail = the corpus must not be indexed; a human investigates the
   flagged chunks listed in the report).
2. A seeded ~10% human-sampling flow: build a review sheet, a human
   records accept/reject verdicts, summarize rolls them up. Sampling is
   deterministic for a given seed so reviews are reproducible and the
   reject rate is an honest estimate over the sampled subset only.

Issue codes:
- ``not_nfc``: text differs from its Unicode NFC normal form
- ``zero_width``: ZWJ/ZWNJ/ZWSP/BOM survived normalization
- ``math_mojibake``: UTF-8 math symbols misread as Latin-1 (double-encoded
                        multiplication, square-root, inequality, ellipsis)
- ``replacement_char``: U+FFFD present
- ``pua_char``: private-use-area glyphs (custom-font residue)
- ``legacy_bijoy``: unconverted Bijoy ASCII signatures present
- ``latin_residue``: a Bangla-rated source passage that is ≥60% ASCII Latin
  letters (unconverted legacy lines the signature test missed); only
  reported when the caller declares the source Bangla-rated
  (``bangla_source=True``), because English curriculum volumes are
  legitimately Latin
"""

from __future__ import annotations

import random
import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from bangla_gpt_api.nctb.bijoy import has_latin_residue, is_likely_legacy_bijoy
from bangla_gpt_api.nctb.normalize import ZERO_WIDTH_CHARS, in_private_use_area

# Classic double-encoded math symbols: a multi-byte UTF-8 lead byte (C2/C3/E2)
# followed by a raw C1/Latin-1-supplement byte. Legitimate Bangla text
# never contains C1 control characters, so this pattern is safe.
_MATH_MOJIBAKE = re.compile("[\u00c2\u00c3\u00e2][\u0080-\u00bf]")

ISSUE_CODES = (
    "not_nfc",
    "zero_width",
    "math_mojibake",
    "replacement_char",
    "pua_char",
    "legacy_bijoy",
    "latin_residue",
)

# Default gate: index rebuilds are blocked when more than this fraction of
# chunks carries at least one QA issue.
DEFAULT_FLAGGED_THRESHOLD = 0.02


def _in_pua(char: str) -> bool:
    return in_private_use_area(char)


def qa_text(text: str, *, bangla_source: bool = False) -> list[str]:
    """Return the sorted list of QA issue codes found in one text.

    ``bangla_source`` additionally applies the ``latin_residue`` verdict; it
    is opt-in because the same ASCII-Latin-dominant passage is a defect in a
    Bangla volume and expected in the English one.
    """
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
    if bangla_source and has_latin_residue(text):
        issues.append("latin_residue")
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
    # RAG-001: duplicate-text rate (additive; older consumers ignore it).
    duplicate_chunks: int = 0
    duplicate_ratio: float = 0.0

    def to_dict(self) -> dict:
        return {
            "total_chunks": self.total_chunks,
            "flagged_chunks": self.flagged_chunks,
            "flagged_ratio": self.flagged_ratio,
            "issues": self.issues,
            "worst": self.worst,
            "pass": self.passed,
            "threshold": self.threshold,
            "duplicate_chunks": self.duplicate_chunks,
            "duplicate_ratio": self.duplicate_ratio,
        }


def qa_chunks(
    chunks: Iterable[Mapping[str, object]],
    *,
    threshold: float = DEFAULT_FLAGGED_THRESHOLD,
    worst_limit: int = 20,
    bangla_source: bool = False,
) -> ChunkQAReport:
    """Run QA over chunk mappings (needs ``chunk_id`` and ``text`` keys)."""
    total = 0
    flagged = 0
    counts: dict[str, int] = {code: 0 for code in ISSUE_CODES}
    worst: list[dict] = []
    seen_texts: set[str] = set()
    duplicates = 0
    for chunk in chunks:
        chunk_id = str(chunk.get("chunk_id", ""))
        text = str(chunk.get("text", ""))
        total += 1
        # RAG-001: identical normalized text indexed twice.
        fingerprint = " ".join(text.split())
        if fingerprint and fingerprint in seen_texts:
            duplicates += 1
        else:
            seen_texts.add(fingerprint)
        issues = qa_text(text, bangla_source=bangla_source)
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
        duplicate_chunks=duplicates,
        duplicate_ratio=round(duplicates / total, 4) if total else 0.0,
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
