"""Extraction-fidelity audit over the built NCTB corpus (A2-02).

Draws a deterministic stratified sample of source pages (strata: source ×
subject × class × content_type), reads every sampled page twice — once from
the pipeline artifact (``data/nctb/extracted/*.pages.json``, produced by
pypdf + the legacy-Bijoy converter) and once independently from the raw PDF —
and classifies the differences:

* ``legacy_encoding_gibberish`` — the source page is legacy-Bijoy encoded and
  the pipeline text is still unconverted;
* ``page_not_usable`` — the source page carries text and the pipeline artifact
  kept nothing usable from it (empty, still legacy, or classified garbage);
* ``broken_conjuncts`` — a documented conjunct reordering artifact
  ("কার্যক্রম" -> "কাযর্ক্রম") survives in the served text;
* ``vowel_sign_misorder`` — a pre-base vowel sign sits directly after a
  virama ("্ি"), which no Bangla word does;
* ``dropped_formula_or_table`` — the source page carries at least 40 math
  characters more than the pipeline text, or the source has column geometry
  the pipeline text lost;
* ``header_footer_noise`` — the running header/footer (volume title + page
  number) is inside the page text: the same opening fragment repeats across
  most pages of the source;
* ``hyphenation`` — the source page carries a line-break hyphen (a line of
  the source ends with "-") that the pipeline text keeps inside a word.

The independent reader is ``pypdfium2`` (PDFium). pymupdf is NOT installed on
this host, so the second engine is recorded honestly instead of claimed; both
engines read the same PDF text layer, so the audit measures PIPELINE-side
damage (conversion, chunking, filtering) and content loss, not text-layer
differences between viewers. Classes that need human judgement are reported
with ``method`` so a row is never read as more than it is.

Usage (from apps/api):
    python scripts/extraction_audit.py --data-dir ../../data/nctb \
        --out ../../data/nctb/extraction_audit.json --sample-size 40
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bangla_gpt_api.data.nctb_loader import LEVEL_CLASS_RANGE, SUBJECT_KEYS  # noqa: E402
from bangla_gpt_api.nctb.bijoy import is_likely_legacy_bijoy  # noqa: E402
from bangla_gpt_api.nctb.normalize import bangla_char_ratio, looks_like_garbage  # noqa: E402

SEED = 20261020
#: Documented conjunct-reordering artifacts measured on this corpus (see
#: docs/NCTB_DATA_PIPELINE.md §3): "কার্যক্রম", "পুস্তক", "বোর্ড".
DOCUMENTED_ARTIFACTS = ("কাযর্ক্রম", "পুস্ত্মক", "বোডর্", "পদাথের্র", "আত্মহত্যা")
_ARTIFACT_RE = re.compile("|".join(re.escape(a) for a in DOCUMENTED_ARTIFACTS))
#: A pre-base vowel sign directly after a virama ("্ি") — no Bangla word has it.
VOWEL_SIGN_RE = re.compile(r"\u09cd[\u09bf\u09c7\u09c8]")
#: Line-break hyphenation in the SOURCE text (a physical line ending with "-").
SOURCE_HYPHEN_BREAK_RE = re.compile(r"-\s*\n")
#: Hyphen kept between two Bangla letters in the pipeline text.
PIPELINE_HYPHEN_RE = re.compile(r"[\u0980-\u09ff]\s?-\s?[\u0980-\u09ff]")
MATH_CHARS = set(
    "0123456789=\u09e6\u09e7\u09e8\u09e9\u09ea\u09eb\u09ec\u09ed\u09ee\u09ef"
    "+\u00d7\u00f7-\u2212\u2264\u2265\u2260\u221a\u00b2\u00b3^%"
)
COLUMN_GAP_RE = re.compile(r"\S {3,}\S")


def _math_char_count(text: str) -> int:
    return sum(1 for char in text if char in MATH_CHARS)


def _load_reports(data_dir: Path) -> dict[str, dict]:
    path = data_dir / "quality_report.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _page_content_type(text: str) -> str:
    """Content type of a PAGE from its own text (loader heuristic, A2-04b)."""
    from bangla_gpt_api.data.nctb_loader import infer_content_type

    return infer_content_type(text)


def _page_types_from_chunks(chunks_dir: Path) -> dict[tuple[str, int], str]:
    """Dominant content_type per (source, page), from the chunk artifacts.

    The catalog class is a CHUNK property; stratifying pages by it therefore
    reads the served chunk types (loader heuristic) over each chunk's page
    range, taking the most frequent type for the page. Pages with no chunk
    keep the page-text inference.
    """
    from bangla_gpt_api.data.nctb_loader import infer_content_type

    mapping: dict[tuple[str, int], str] = {}
    for path in sorted(chunks_dir.glob("*.chunks.jsonl")):
        source_id = path.name.removesuffix(".chunks.jsonl")
        per_page: dict[int, Counter] = defaultdict(Counter)
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            start = row.get("page_start")
            end = row.get("page_end")
            if start is None or end is None:
                continue
            label = infer_content_type(str(row.get("text", "")))
            for page in range(int(start), int(end) + 1):
                per_page[page][label] += 1
        for page, counts in per_page.items():
            mapping[(source_id, page)] = counts.most_common(1)[0][0]
    return mapping


def _frame(data_dir: Path) -> list[dict[str, Any]]:
    """One row per extracted page: source, page, subject, class, type."""
    reports = _load_reports(data_dir)
    chunk_types = _page_types_from_chunks(data_dir / "normalized")
    rows: list[dict[str, Any]] = []
    for path in sorted((data_dir / "extracted").glob("*.pages.json")):
        source_id = path.name.removesuffix(".pages.json")
        report = reports.get(source_id, {})
        level = report.get("level")
        low_high = LEVEL_CLASS_RANGE.get(level) if level else None
        if low_high is None:
            continue
        subject = SUBJECT_KEYS.get(report.get("subject_bn", ""), "general")
        payload = json.loads(path.read_text(encoding="utf-8"))
        for page in payload.get("pages", []):
            text = page.get("text") or ""
            if not text.strip():
                continue
            rows.append(
                {
                    "source": source_id,
                    "file_name": reports.get(source_id, {}).get("file_name", ""),
                    "page": int(page["page_number"]),
                    "subject": subject,
                    "level": level,
                    "class_range": list(low_high),
                    "content_type": chunk_types.get(
                        (source_id, int(page["page_number"])), _page_content_type(text)
                    ),
                    "pipeline_chars": len(text),
                    "bangla_rated": float(report.get("bangla_char_ratio_on_usable", 0.0)) >= 0.5,
                }
            )
    return rows


def _stratified_sample(frame: list[dict[str, Any]], size: int, seed: int) -> list[dict]:
    """Deterministic sample: round-robin across (subject, class_range, type).

    Round-robin (rather than proportional allocation) keeps small strata
    represented, which is the point of a stratified audit: a class or content
    type that exists in the corpus must appear in the sample even when it is a
    minority of pages.
    """
    rng = random.Random(seed)  # noqa: S311 - sampling, not security
    strata: dict[tuple[str, int, str], list[dict]] = defaultdict(list)
    for row in frame:
        strata[(row["subject"], row["class_range"][0], row["content_type"])].append(row)
    for rows in strata.values():
        rng.shuffle(rows)
    keys = sorted(strata)
    rng.shuffle(keys)
    sample: list[dict] = []
    index = 0
    while len(sample) < size and any(strata[key] for key in keys):
        key = keys[index % len(keys)]
        index += 1
        if strata[key]:
            sample.append(strata[key].pop())
    return sample


def _pdfium():
    """The independent second reader (PDFium), imported on demand.

    Deliberately NOT a declared dependency: it ships native pdfium binaries
    per platform (~10 MB each) and is needed only by this audit script, so a
    dev/CI install must not pull it in. The ratchet's deps gate records the
    import as an accepted finding (pyproject.toml, [tool.deptry]); the error
    below is what an operator sees when the reader is absent.
    """
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:  # pragma: no cover - environment-dependent
        raise SystemExit(
            "extraction_audit needs the independent second reader: "
            "pip install pypdfium2 (PDFium). It is intentionally not a declared "
            "dependency; see pyproject.toml [tool.deptry]."
        ) from exc
    return pdfium


def _source_page_text(pdf_path: Path, page_number: int) -> str:
    """Independent read of the source page text (PDFium)."""
    pdfium = _pdfium()

    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        if page_number < 1 or page_number > len(doc):
            return ""
        return doc[page_number - 1].get_textpage().get_text_range()
    finally:
        doc.close()


def _page_ink_ratio(pdf_path: Path, page_number: int, dpi: int = 40) -> float:
    """Fraction of dark pixels when the page is rendered small (content proxy)."""
    pdfium = _pdfium()

    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        if page_number < 1 or page_number > len(doc):
            return 0.0
        bitmap = doc[page_number - 1].render(scale=dpi / 72, grayscale=True)
        image = bitmap.to_pil()
        histogram = image.histogram()  # 256 buckets, mode "L"
        total = sum(histogram)
        dark = sum(histogram[:128])
        return round(dark / total, 4) if total else 0.0
    finally:
        doc.close()


def _running_header_prefixes(data_dir: Path) -> dict[str, set[str]]:
    """Opening fragments that repeat across most pages of a source.

    A fragment shared by at least 5 pages of the same volume is a running
    header/footer (volume title + page number), not content.
    """
    prefixes: dict[str, set[str]] = {}
    for path in sorted((data_dir / "extracted").glob("*.pages.json")):
        source_id = path.name.removesuffix(".pages.json")
        seen: Counter = Counter()
        for page in json.loads(path.read_text(encoding="utf-8")).get("pages", []):
            text = (page.get("text") or "").strip()
            if not text:
                continue
            seen[re.sub(r"\d+", "#", text[:28])] += 1
        prefixes[source_id] = {prefix for prefix, count in seen.items() if count >= 5}
    return prefixes


def _classify(
    pipeline: str,
    source: str,
    ink_ratio: float,
    *,
    running_prefixes: set[str],
    bangla_rated: bool = True,
) -> dict[str, Any]:
    """Error classes for one page (machine-classified unless stated)."""
    pipeline_math = _math_char_count(pipeline)
    source_math = _math_char_count(source)
    prefix = re.sub(r"\d+", "#", pipeline.strip()[:28])
    return {
        "legacy_encoding_gibberish": bool(
            is_likely_legacy_bijoy(source) and is_likely_legacy_bijoy(pipeline)
        ),
        # source carried text and the pipeline kept nothing usable from it:
        # an empty page artifact (always a defect) or, for a Bangla-rated
        # source, text the converter left legacy/garbage (the English volume is
        # legitimately Latin, so the ratio verdict is scoped like the QA gate).
        "page_not_usable": bool(
            len(re.sub(r"\s", "", source)) >= 100
            and (
                not pipeline.strip()
                or (
                    bangla_rated
                    and (bangla_char_ratio(pipeline) < 0.5 or looks_like_garbage(pipeline))
                )
            )
        ),
        "broken_conjuncts": len(_ARTIFACT_RE.findall(pipeline)),
        "vowel_sign_misorder": len(VOWEL_SIGN_RE.findall(pipeline)),
        "dropped_formula_or_table": bool(
            source_math - pipeline_math >= 40
            or (
                len(COLUMN_GAP_RE.findall(source)) >= 2
                and len(COLUMN_GAP_RE.findall(pipeline)) == 0
            )
        ),
        "header_footer_noise": prefix != "" and prefix in running_prefixes,
        "hyphenation": bool(SOURCE_HYPHEN_BREAK_RE.search(source))
        and bool(PIPELINE_HYPHEN_RE.search(pipeline)),
        "pipeline_math_chars": pipeline_math,
        "source_math_chars": source_math,
        "ink_ratio": ink_ratio,
    }


def audit(data_dir: Path, sample_size: int, seed: int) -> dict[str, Any]:
    frame = _frame(data_dir)
    sample = _stratified_sample(frame, sample_size, seed)
    running_prefixes = _running_header_prefixes(data_dir)
    rows: list[dict[str, Any]] = []
    for entry in sample:
        raw_dir = data_dir / "raw"
        candidates = list(raw_dir.glob(f"*{entry['source'].removeprefix('nctb-')[:16]}*.pdf"))
        pdf_path = candidates[0] if candidates else None
        pipeline = ""
        source_text = ""
        ink = 0.0
        if pdf_path is not None:
            pages_path = data_dir / "extracted" / f"{entry['source']}.pages.json"
            payload = json.loads(pages_path.read_text(encoding="utf-8"))
            for page in payload.get("pages", []):
                if int(page["page_number"]) == entry["page"]:
                    pipeline = page.get("text") or ""
                    break
            source_text = _source_page_text(pdf_path, entry["page"])
            ink = _page_ink_ratio(pdf_path, entry["page"])
        row = {
            **entry,
            "pdf": pdf_path.name if pdf_path else "",
            "source_chars": len(source_text),
            **_classify(
                pipeline,
                source_text,
                ink,
                running_prefixes=running_prefixes.get(entry["source"], set()),
                bangla_rated=bool(entry.get("bangla_rated", True)),
            ),
        }
        rows.append(row)

    per_class: dict[str, dict[str, Any]] = {}
    class_keys = (
        "legacy_encoding_gibberish",
        "page_not_usable",
        "dropped_formula_or_table",
        "header_footer_noise",
    )
    for key in class_keys:
        pages = [f"{r['source']}:p{r['page']}" for r in rows if r[key]]
        per_class[key] = {
            "pages": len(pages),
            "rate": round(len(pages) / len(rows), 4) if rows else 0.0,
            "page_refs": pages[:20],
            "method": "machine-classified",
        }
    for key, label in (
        ("broken_conjuncts", "conjunct_reorder_artifact"),
        ("vowel_sign_misorder", "vowel_sign_misorder"),
        ("hyphenation", "hyphenation"),
    ):
        pages = [f"{r['source']}:p{r['page']}" for r in rows if r[key]]
        occurrences = sum(int(r[key]) for r in rows)
        per_class[label] = {
            "pages": len(pages),
            "occurrences": occurrences,
            "rate": round(len(pages) / len(rows), 4) if rows else 0.0,
            "page_refs": pages[:20],
            "method": "machine-classified (pattern counts; the sane/suspect "
            "judgement of an individual word needs a human read)",
        }
    ink_without_text = [
        f"{r['source']}:p{r['page']}"
        for r in rows
        if r["ink_ratio"] >= 0.06 and r["pipeline_chars"] < 400
    ]
    per_class["ink_without_text"] = {
        "pages": len(ink_without_text),
        "page_refs": ink_without_text[:20],
        "method": "machine-classified (rendered-page ink fraction vs text "
        "length: figures/tables that are not represented in the text)",
    }
    return {
        "seed": seed,
        "sample_size": len(rows),
        "frame_pages": len(frame),
        "strata": {
            f"{subject}|class{low}|{content_type}": count
            for (subject, low, content_type), count in sorted(
                Counter(
                    (r["subject"], r["class_range"][0], r["content_type"]) for r in frame
                ).items()
            )
        },
        "sample": rows,
        "error_classes": per_class,
    }


def _markdown(report: dict) -> str:
    lines = [
        "| Error class | Pages affected | Rate | Method | Example page refs |",
        "|---|---|---|---|---|",
    ]
    for name, block in report["error_classes"].items():
        refs = ", ".join(block["page_refs"][:3]) or "—"
        rate = f"{block.get('rate', 0.0):.1%}" if "rate" in block else "—"
        lines.append(
            f"| `{name}` | {block['pages']} / {report['sample_size']} | {rate} | "
            f"{block['method']} | {refs} |"
        )
    return "\n".join(lines)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("../../data/nctb"))
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--sample-size", type=int, default=40)
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args()

    report = audit(args.data_dir, args.sample_size, args.seed)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    print(f"sampled {report['sample_size']} pages of {report['frame_pages']}")
    print(_markdown(report))
    print(f"json: {args.out}" if args.out else "(no --out)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
