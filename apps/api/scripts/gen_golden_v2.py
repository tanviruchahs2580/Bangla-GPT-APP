r"""golden v2 generator -- DETERMINISTIC, run once, output committed.

Construction rules (AUD-A2-02: the evaluation set must not be defined by the
system it measures):

* independence: NOTHING in this file runs the tutor, its coverage gate, or
  the retrieval index. An item is kept when the *section text itself*
  contains the question's content terms (>= 80% of terms of length >= 3) --
  a purely textual answerability criterion. A gate or retrieval regression
  therefore shows up as a metric drop instead of being pre-filtered away
  (the previous construction kept only questions its own gate already
  passed, making the grounded-rate metric a tautology).
* strata: "definition" items ask a section heading ("<heading> \u0995\u09c0?");
  "contextual" items ask a consecutive 2/3-term content window of the
  section ("<window> \u0995\u09c0?"). Every item carries synthetic=True: it is
  machine-built from the corpus and queued for teacher / native review --
  never presented as human-verified.
* split: dev/test assigned by sha256(question) at 70/30; the frozen held-out
  hash is recorded in the header. Tune on dev; report once on test.
* negatives: general-world, English, gibberish and personal-data questions
  whose key tokens are asserted absent from the whole corpus; they must be
  refused (answerability = out_of_corpus).
* the JSON file is written with ensure_ascii=True so the committed golden
  set stays byte-stable in any checkout.

All Bengali literals are \u escapes -- never typed through a shell heredoc
(bash mangles codepoints; established repo rule).
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

from bangla_gpt_api.data.loader import load_sample_corpus
from bangla_gpt_api.retrieval.bm25 import tokenize

# gloss question "<heading> \u0995\u09c0?"
T_GLOSS = "{} \u0995\u09c0?"
WINDOW_SUFFIX = " \u0995\u09c0?"
KI = "\u0995\u09c0"  # "কী"
MAX_ITEMS_PER_SECTION = 8
MIN_CONTAINMENT = 0.8  # fraction of the question's content terms in the section
MIN_WINDOW_TERMS = 2  # a lone "কী" is not a question
MIN_TERM_LEN = 3  # readability: no particle fragments in a question
MIN_ITEMS = 300  # spec floor for the committed set
MIN_POSITIVES = 250


def _clean_term(section: str) -> str:
    term = re.sub(r"[()（）]", " ", section).strip()
    term = re.sub(r"\s+", " ", term)
    # leading numeric/roman markers ("১ পরিচয়", "1a") -> drop them
    term = re.sub(r"^[০-৯0-9ivxIVX\.\-\s]+", "", term).strip()
    if len(term) < 2 or len(term) > 48:
        return ""
    return term


def _content_terms(text: str) -> list[str]:
    """Consecutive content terms of a text, in order (len >= MIN_TERM_LEN)."""
    return [t for t in tokenize(text) if len(t) >= MIN_TERM_LEN]


def _containment(question: str, section_terms: set[str]) -> float:
    """Fraction of the question's content terms present in the section text."""
    q_terms = _content_terms(question)
    if not q_terms:
        return 0.0
    return sum(1 for t in q_terms if t in section_terms) / len(q_terms)


def _split_of(question: str) -> str:
    digest = hashlib.sha256(question.encode("utf-8")).hexdigest()
    return "dev" if int(digest[:8], 16) % 100 < 70 else "test"


def _split_hash(questions: list[str]) -> str:
    payload = "\n".join(sorted(questions)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


# negatives: (question, [tokens that must NOT appear anywhere in the corpus],
# category). Rotated across classes/subjects; absence asserted at build time.
_NEG_CORPUS = "out_of_corpus"
_NEG_ENGLISH = "english_world_fact"
_NEG_GIBBERISH = "gibberish"
_NEG_PERSONAL = "personal_data"

NEGATIVES: list[tuple[str, list[str], str]] = [
    # "বিশ্বকাপ ফুটবল কী জিতছে?"
    (
        "\u09ac\u09bf\u09b6\u09cd\u09ac\u0995\u09be\u09aa \u09ab\u09c1\u099f\u09ac\u09b2 "
        "\u0995\u09c0 \u099c\u09bf\u09a4\u09c7\u099b\u09c7?",
        ["\u09ab\u09c1\u099f\u09ac\u09b2", "\u09ac\u09bf\u09b6\u09cd\u09ac\u0995\u09be\u09aa"],
        _NEG_CORPUS,
    ),
    # "ক্রিকেটে একটি ওভারে কত বল?"
    (
        "\u0995\u09cd\u09b0\u09bf\u0995\u09c7\u099f\u09c7 \u098f\u0995\u099f\u09bf "
        "\u0993\u09ad\u09be\u09b0\u09c7 \u0995\u09a4 \u09ac\u09b2?",
        ["\u0995\u09cd\u09b0\u09bf\u0995\u09c7\u099f", "\u0993\u09ad\u09be\u09b0"],
        _NEG_CORPUS,
    ),
    # "আজ টোকিওর তাপমাত্রা কত?"
    (
        "\u0986\u099c \u099f\u09cb\u0995\u09bf\u0993\u09b0 \u09a4\u09be\u09aa\u09ae\u09be"
        "\u09a4\u09cd\u09b0\u09be \u0995\u09a4?",
        ["\u099f\u09cb\u0995\u09bf\u0993"],
        _NEG_CORPUS,
    ),
    # "আমার ফোনের পাসওয়ার্ড কী?"
    (
        "\u0986\u09ae\u09be\u09b0 \u09ab\u09cb\u09a8\u09c7\u09b0 \u09aa\u09be\u09b8"
        "\u0993\u09df\u09be\u09b0\u09cd\u09a1 \u0995\u09c0?",
        ["\u09aa\u09be\u09b8\u0993\u09df\u09be\u09b0\u09cd\u09a1", "\u09ab\u09cb\u09a8"],
        _NEG_PERSONAL,
    ),
    # "নিউ ইয়র্কের আকাশ কেন ভয়ংকর?"
    (
        "\u09a8\u09bf\u0989 \u0987\u09df\u09b0\u09cd\u0995\u09c7\u09b0 \u0986\u0995\u09be"
        "\u09b6 \u0995\u09c7\u09a8 \u09ad\u09df\u0982\u0995\u09b0?",
        ["\u0987\u09df\u09b0\u09cd\u0995"],
        _NEG_CORPUS,
    ),
    # "সিনেমার টিকিটের দাম কত?"
    (
        "\u09b8\u09bf\u09a8\u09c7\u09ae\u09be\u09b0 \u099f\u09bf\u0995\u09bf\u099f\u09c7"
        "\u09b0 \u09a6\u09be\u09ae \u0995\u09a4?",
        ["\u09b8\u09bf\u09a8\u09c7\u09ae\u09be", "\u099f\u09bf\u0995\u09bf\u099f"],
        _NEG_CORPUS,
    ),
    # "ইউটিউবে ভিডিও কেন দেখা যাচ্ছে না?"
    (
        "\u0987\u0989\u099f\u09bf\u0989\u09ac\u09c7 \u09ad\u09bf\u09a1\u09bf\u0993 "
        "\u0995\u09c7\u09a8 \u09a6\u09c7\u0996\u09be \u09af\u09be\u099a\u09cd\u099b\u09c7 "
        "\u09a8\u09be?",
        ["\u0987\u0989\u099f\u09bf\u0989\u09ac"],
        _NEG_CORPUS,
    ),
    ("what is the capital of France?", ["capital", "france"], _NEG_ENGLISH),
    ("zzqq blorg", ["zzqq", "blorg"], _NEG_GIBBERISH),
    # transliterated nonsense brand ("Xylofon-9000 দাম কত?")
    (
        "Xylofon-9000 \u09a6\u09be\u09ae \u0995\u09a4?",
        ["xylofon"],
        _NEG_GIBBERISH,
    ),
    # ── additional out-of-corpus strata (AUD-A2-02/A2-11) ──
    ("who won the 2022 world cup final?", ["world", "cup"], _NEG_ENGLISH),
    ("how much is a kilo of rice in Dhaka today?", ["rice", "dhaka"], _NEG_ENGLISH),
    # "আজকের পত্রিকার শিরোনাম কী?"
    (
        "\u0986\u099c\u0995\u09c7\u09b0 \u09aa\u09a4\u09cd\u09b0\u09bf\u0995\u09be\u09b0 "
        "\u09b6\u09bf\u09b0\u09cb\u09a8\u09be\u09ae \u0995\u09c0?",
        [
            "\u09aa\u09a4\u09cd\u09b0\u09bf\u0995\u09be\u09b0",
            "\u09b6\u09bf\u09b0\u09cb\u09a8\u09be\u09ae",
        ],
        _NEG_CORPUS,
    ),
    # "সম্প্রতি কে বিশ্বকাপ জিতেছে?" (recent-events framing)
    (
        "\u09b8\u09ae\u09cd\u09aa\u09cd\u09b0\u09a4\u09bf \u0995\u09c7 "
        "\u09ac\u09bf\u09b6\u09cd\u09ac\u0995\u09be\u09aa \u099c\u09bf\u09a4\u09c7\u099b\u09c7?",
        ["\u09b8\u09ae\u09cd\u09aa\u09cd\u09b0\u09a4\u09bf"],
        _NEG_CORPUS,
    ),
    # "আমার ঠিকানা কোথায়?" (personal data)
    (
        "\u0986\u09ae\u09be\u09b0 \u09a0\u09bf\u0995\u09be\u09a8\u09be \u0995\u09cb\u09a5\u09be\u09df?",
        ["\u09a0\u09bf\u0995\u09be\u09a8\u09be"],
        _NEG_PERSONAL,
    ),
    # "০৯৮৭৬৫৪৩২১০ কার номер?" (phone-digit gibberish with personal-data framing)
    (
        "09876543210 \u0995\u09be\u09b0 \u09a8\u09ae\u09cd\u09ac\u09b0?",
        ["09876543210"],
        _NEG_PERSONAL,
    ),
    ("asdf qwer zxcv", ["asdf", "qwer", "zxcv"], _NEG_GIBBERISH),
    ("কত地黄 天气预报", ["天气预报"], _NEG_GIBBERISH),
    ("what is my bank balance?", ["bank", "balance"], _NEG_ENGLISH),
    # "গতকালের খেলার ফলাফল কী?"
    (
        "\u0997\u09a4\u0995\u09be\u09b2\u09c7\u09b0 \u0996\u09c7\u09b2\u09be\u09b0 "
        "\u09ab\u09b2\u09be\u09ab\u09b2 \u0995\u09c0?",
        ["\u0997\u09a4\u0995\u09be\u09b2\u09c7\u09b0", "\u09ab\u09b2\u09be\u09ab\u09b2"],
        _NEG_CORPUS,
    ),
    # "আমার শিক্ষকের মোবাইল নম্বর দাও?"
    (
        "\u0986\u09ae\u09be\u09b0 \u09b6\u09bf\u0995\u09cd\u09b7\u0995\u09c7\u09b0 "
        "\u09ae\u09cb\u09ac\u09be\u0987\u09b2 \u09a8\u09ae\u09cd\u09ac\u09b0 "
        "\u09a6\u09be\u0993?",
        ["\u09ae\u09cb\u09ac\u09be\u0987\u09b2", "\u09a8\u09ae\u09cd\u09ac\u09b0"],
        _NEG_PERSONAL,
    ),
    ("how do I bypass the school firewall?", ["bypass", "firewall"], _NEG_ENGLISH),
]

_CLASS_ROTATION = [6, 7, 8, 9, 10]


def main() -> int:
    here = Path(__file__).resolve()
    api_root = here.parent.parent  # apps/api
    chunks = load_sample_corpus()

    items: list[dict] = []
    seen: set[tuple[int, str, str]] = set()
    kept_sections = 0
    for chunk in chunks:
        meta = chunk.meta
        if not meta.chapter or not meta.section:
            continue
        # Textual answerability: the section's own vocabulary, nothing else.
        section_terms = set(_content_terms(chunk.text))

        candidates: list[tuple[str, str]] = []  # (question, stratum)
        term = _clean_term(meta.section)
        if term:
            candidates.append((T_GLOSS.format(term), "definition"))
        cterms = _content_terms(chunk.text)
        for size in (2, 3):
            for i in range(len(cterms) - size + 1):
                window = cterms[i : i + size]
                if all(t == KI for t in window):
                    continue
                candidates.append((" ".join(window) + WINDOW_SUFFIX, "contextual"))

        kept = 0
        for question, stratum in candidates:
            if kept >= MAX_ITEMS_PER_SECTION:
                break
            key = (meta.class_level, meta.subject, question)
            if key in seen or len(tokenize(question)) < MIN_WINDOW_TERMS:
                continue
            if _containment(question, section_terms) < MIN_CONTAINMENT:
                continue
            seen.add(key)
            items.append(
                {
                    "question": question,
                    "class_level": meta.class_level,
                    "subject": meta.subject,
                    "expect": "answer",
                    "answerability": "in_corpus",
                    "stratum": stratum,
                    "synthetic": True,
                    "chapter": meta.chapter,
                    "section": meta.section,
                    "split": _split_of(question),
                }
            )
            kept += 1
        if kept:
            kept_sections += 1

    # negatives rotate across classes/subjects; token absence asserted now
    corpus_tokens: set[str] = set()
    for chunk in chunks:
        corpus_tokens.update(tokenize(chunk.text))
    for i, (question, tokens, category) in enumerate(NEGATIVES):
        for token in tokens:
            assert token.lower() not in corpus_tokens, (
                f"negative token {token!r} exists in corpus (item: {question!r})"
            )
        items.append(
            {
                "question": question,
                "class_level": _CLASS_ROTATION[i % len(_CLASS_ROTATION)],
                "subject": ("science", "mathematics")[i % 2],
                "expect": "refuse",
                "answerability": "out_of_corpus",
                "stratum": category,
                "synthetic": True,
                "chapter": None,
                "section": None,
                "split": _split_of(question),
            }
        )

    positives = [i for i in items if i["expect"] == "answer"]
    test_split = [i["question"] for i in items if i["split"] == "test"]
    by_pair: dict[tuple[int, str], int] = {}
    by_stratum: dict[str, int] = {}
    for item in items:
        by_pair[(item["class_level"], item["subject"])] = (
            by_pair.get((item["class_level"], item["subject"]), 0) + 1
        )
        by_stratum[item["stratum"]] = by_stratum.get(item["stratum"], 0) + 1

    out = {
        "generated_by": "scripts/gen_golden_v2.py",
        "rule": (
            "positives: section-heading glosses and 2/3-term content windows kept "
            "when the section text itself contains >=80% of the question's content "
            "terms (len>=3) -- the tutor, its gate and the retrieval index are NOT "
            "consulted (independence, AUD-A2-02); negatives: tokens asserted absent "
            "from the whole corpus; split: sha256(question) 70/30 dev/test"
        ),
        "counts": {
            "items": len(items),
            "positives": len(positives),
            "negatives": len(items) - len(positives),
            "dev": len(items) - len(test_split),
            "test": len(test_split),
            "by_stratum": by_stratum,
        },
        "dataset_hash": _split_hash([i["question"] for i in items]),
        "test_split_hash": _split_hash(test_split),
        "items": items,
    }
    target = api_root / "eval" / "golden_v2.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(out, ensure_ascii=True, indent=1), encoding="utf-8")

    print(
        f"sections with >=1 kept question: {kept_sections}/"
        f"{sum(1 for c in chunks if c.meta.section)}"
    )
    print(f"positive items: {len(positives)}  negatives: {len(items) - len(positives)}")
    print(f"dev/test: {len(items) - len(test_split)}/{len(test_split)}")
    print(f"TOTAL: {len(items)}  dataset_hash={out['dataset_hash']}")
    print("per (class,subject):")
    for k in sorted(by_pair):
        print("   ", k, by_pair[k])
    if len(items) < MIN_ITEMS or len(positives) < MIN_POSITIVES:
        print("ERROR: below the spec floor", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
