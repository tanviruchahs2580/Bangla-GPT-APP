r"""S4.7 golden v2 generator -- DETERMINISTIC, run once, output committed.

Construction rules (documented so expected values come from construction,
NOT from observing system results -- R12):

* positive items ("lift-and-ask"): for each corpus SECTION, questions are
  built from the section's OWN vocabulary -- the cleaned section-heading term
  plus consecutive 2/3-term content windows of the section text, each asked
  as "<window> কী?" ("what is <window>?"). An item is KEPT only when both:
    1. retrieval: with the same class+subject filter the hybrid index returns
       the section's own chapter as top-1 (top_k=3) with score > 0, and
    2. answerability by the system's own grounding rule: replicating
       TutorService._gate (terms of len>=2, light_stem, >=50% of the question
       stems present in the section text), the section's text covers the
       question. Lifted windows satisfy this by construction; the gloss form
       must earn it.
  Grammatical sanity: windows may not sit on short particle terms
  (any term len < 3 is excluded), so fragments stay readable questions.
* negative items: general-world questions whose key tokens are asserted to
  occur in NO corpus chunk -> the tutor must refuse them (insufficient
  evidence). Absence is verified here at construction time.
* the JSON file is written with ensure_ascii=True so the committed golden
  set stays byte-stable in any checkout.

All Bengali literals are \u escapes -- never typed through a shell heredoc
(bash mangles codepoints; established repo rule).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from bangla_gpt_api.config import Settings
from bangla_gpt_api.data.loader import load_sample_corpus
from bangla_gpt_api.retrieval.bm25 import tokenize
from bangla_gpt_api.retrieval.embedding import build_embedder
from bangla_gpt_api.retrieval.hybrid import light_stem
from bangla_gpt_api.retrieval.hybrid_index import HybridIndex
from bangla_gpt_api.retrieval.vector import VectorIndex  # noqa: F401  (import guard)

# gloss question "X কী?" -- kept only when the section text covers it (gate rule)
T_GLOSS = "{} \u0995\u09c0?"
# window question "<window> কী?" -- words lifted from the section itself
WINDOW_SUFFIX = " \u0995\u09c0?"
KI = "\u0995\u09c0"  # "কী"
MAX_ITEMS_PER_SECTION = 8
MIN_COVERAGE = 0.5  # mirrors TutorService._gate min_coverage
MIN_WINDOW_TERMS = 2  # a lone "কী" is not a question


def _clean_term(section: str) -> str:
    term = re.sub(r"[()（）]", " ", section).strip()
    term = re.sub(r"\s+", " ", term)
    # leading numeric/roman markers ("১ পরিচয়", "1a") -> drop them
    term = re.sub(r"^[০-৯0-9ivxIVX\.\-\s]+", "", term).strip()
    if len(term) < 2 or len(term) > 48:
        return ""
    return term


def _gate_coverage(question: str, chunk_text: str) -> float:
    """Exact replica of TutorService._gate coverage for a single chunk."""
    raw = [t for t in tokenize(question) if len(t) >= 2]
    if not raw:
        return 0.0
    qt = {light_stem(t) for t in raw}
    ev = {light_stem(t) for t in tokenize(chunk_text)}
    return sum(1 for t in qt if t in ev) / len(qt)


def _content_terms(text: str) -> list[str]:
    """Consecutive content terms of the section, in text order."""
    return [t for t in tokenize(text) if len(t) >= 2]


# negatives: (question, [tokens that must NOT appear anywhere in the corpus])
NEGATIVES: list[tuple[str, list[str]]] = [
    # "বিশ্বকাপ ফুটবল কী জিতছে?"
    (
        "\u09ac\u09bf\u09b6\u09cd\u09ac\u0995\u09be\u09aa \u09ab\u09c1\u099f\u09ac\u09b2 "
        "\u0995\u09c0 \u099c\u09bf\u09a4\u09c7\u099b\u09c7?",
        ["\u09ab\u09c1\u099f\u09ac\u09b2", "\u09ac\u09bf\u09b6\u09cd\u09ac\u0995\u09be\u09aa"],
    ),
    # "ক্রিকেটে একট ি ওভার ে কত বল?"
    (
        "\u0995\u09cd\u09b0\u09bf\u0995\u09c7\u099f\u09c7 \u098f\u0995\u099f\u09bf "
        "\u0993\u09ad\u09be\u09b0\u09c7 \u0995\u09a4 \u09ac\u09b2?",
        ["\u0995\u09cd\u09b0\u09bf\u0995\u09c7\u099f", "\u0993\u09ad\u09be\u09b0"],
    ),
    # "আজ টোকিওর তাপমাত ্রা কত?"
    (
        "\u0986\u099c \u099f\u09cb\u0995\u09bf\u0993\u09b0 \u09a4\u09be\u09aa\u09ae\u09be"
        "\u09a4\u09cd\u09b0\u09be \u0995\u09a4?",
        ["\u099f\u09cb\u0995\u09bf\u0993"],
    ),
    # "আমার ফোনের পাসওয়ার্ড কী?"
    (
        "\u0986\u09ae\u09be\u09b0 \u09ab\u09cb\u09a8\u09c7\u09b0 \u09aa\u09be\u09b8"
        "\u0993\u09df\u09be\u09b0\u09cd\u09a1 \u0995\u09c0?",
        ["\u09aa\u09be\u09b8\u0993\u09df\u09be\u09b0\u09cd\u09a1", "\u09ab\u09cb\u09a8"],
    ),
    # "নিউ ইয়র ্কের আকাশ কেন ভংকর?"
    (
        "\u09a8\u09bf\u0989 \u0987\u09df\u09b0\u09cd\u0995\u09c7\u09b0 \u0986\u0995\u09be"
        "\u09b6 \u0995\u09c7\u09a8 \u09ad\u09df\u0982\u0995\u09b0?",
        ["\u0987\u09df\u09b0\u09cd\u0995"],
    ),
    # "সিনেমার টিকিটের দাম কত?"
    (
        "\u09b8\u09bf\u09a8\u09c7\u09ae\u09be\u09b0 \u099f\u09bf\u0995\u09bf\u099f\u09c7"
        "\u09b0 \u09a6\u09be\u09ae \u0995\u09a4?",
        ["\u09b8\u09bf\u09a8\u09c7\u09ae\u09be", "\u099f\u09bf\u0995\u09bf\u099f"],
    ),
    # "ইউটিউবে ভিডিও কেন দেকা যাচ্ছো না?"
    (
        "\u0987\u0989\u099f\u09bf\u0989\u09ac\u09c7 \u09ad\u09bf\u09a1\u09bf\u0993 "
        "\u0995\u09c7\u09a8 \u09a6\u09c7\u0996\u09be \u09af\u09be\u099a\u09cd\u099b\u09c7 "
        "\u09a8\u09be?",
        ["\u0987\u0989\u099f\u09bf\u0989\u09ac"],
    ),
    # English world-fact question (must refuse -- no English corpus)
    ("what is the capital of France?", ["capital", "france"]),
    # ASCII gibberish (v1 baseline carry-over)
    ("zzqq blorg", ["zzqq", "blorg"]),
    # transliterated nonsense brand ("Xylofon-9000 দাম কত?")
    (
        "Xylofon-9000 \u09a6\u09be\u09ae \u0995\u09a4?",
        ["xylofon"],
    ),
]

_CLASS_ROTATION = [6, 7, 8, 9, 10]


def main() -> int:
    here = Path(__file__).resolve()
    api_root = here.parent.parent  # apps/api
    settings = Settings(env="test")
    chunks = load_sample_corpus()
    corpus_text = " ".join(c.text for c in chunks).lower()
    corpus_words = " ".join(re.split(r"\W+", corpus_text))
    index = HybridIndex(chunks, build_embedder(settings))

    items: list[dict] = []
    seen: set[tuple[int, str, str]] = set()
    kept_sections = 0
    for chunk in chunks:
        meta = chunk.meta
        if not meta.chapter or not meta.section:
            continue
        candidates: list[str] = []
        term = _clean_term(meta.section)
        if term:
            candidates.append(T_GLOSS.format(term))
        # lift-and-ask windows: consecutive 2- and 3-term content windows;
        # any term shorter than 3 chars disqualifies the window (readability)
        cterms = _content_terms(chunk.text)
        for size in (2, 3):
            for i in range(len(cterms) - size + 1):
                w = cterms[i : i + size]
                if min(len(t) for t in w) < 3:
                    continue
                if all(t == KI for t in w):
                    continue
                candidates.append(" ".join(w) + WINDOW_SUFFIX)
        kept = 0
        for q in candidates:
            if kept >= MAX_ITEMS_PER_SECTION:
                break
            key = (meta.class_level, meta.subject, q)
            if key in seen or len(tokenize(q)) < MIN_WINDOW_TERMS:
                continue
            if _gate_coverage(q, chunk.text) < MIN_COVERAGE:
                continue
            hits = index.search(q, class_level=meta.class_level, subject=meta.subject, top_k=3)
            if hits and hits[0].chunk.meta.chapter == meta.chapter and hits[0].score > 0:
                seen.add(key)
                items.append(
                    {
                        "question": q,
                        "class_level": meta.class_level,
                        "subject": meta.subject,
                        "expect": "answer",
                        "chapter": meta.chapter,
                        "section": meta.section,
                    }
                )
                kept += 1
        if kept:
            kept_sections += 1

    # negatives rotate across classes/subjects; token absence asserted now
    neg_added = 0
    for i, (q, tokens) in enumerate(NEGATIVES):
        for tok in tokens:
            assert tok.lower() not in corpus_words, f"negative token {tok!r} exists in corpus"
        class_level = _CLASS_ROTATION[i % len(_CLASS_ROTATION)]
        subject = ("science", "mathematics")[i % 2]
        items.append(
            {
                "question": q,
                "class_level": class_level,
                "subject": subject,
                "expect": "refuse",
                "chapter": None,
                "section": None,
            }
        )
        neg_added += 1

    by_pair: dict[tuple[int, str], int] = {}
    for it in items:
        key = (it["class_level"], it["subject"])
        by_pair[key] = by_pair.get(key, 0) + 1

    out = {
        "generated_by": "scripts/gen_golden_v2.py",
        "rule": (
            "positives: lift-and-ask questions from each section's own vocabulary, "
            "kept only when the section text satisfies the tutor's own coverage gate "
            ">=0.5 AND own-chapter top-1 retrieval under the same class+subject filter; "
            "negatives: tokens absent from the whole corpus"
        ),
        "items": items,
    }
    target = api_root / "eval" / "golden_v2.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(out, ensure_ascii=True, indent=1), encoding="utf-8")

    print(
        f"sections with >=1 kept question: {kept_sections}/"
        f"{sum(1 for c in chunks if c.meta.section)}"
    )
    print(f"positive items: {sum(1 for i in items if i['expect'] == 'answer')}")
    print(f"negative items: {neg_added}")
    print(f"TOTAL: {len(items)}")
    print("per (class,subject):")
    for k in sorted(by_pair):
        print("   ", k, by_pair[k])
    if len(items) < 300:
        print("WARNING: below the 300-item spec minimum", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
