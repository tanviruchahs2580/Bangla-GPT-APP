"""Hybrid-retrieval helpers over the lexical BM25 baseline.

Three recall boosters, all deterministic and dependency-free:

1. ``light_stem`` — conservative Bangla inflection stripper so that
   ``ভগ্নাংশের`` matches ``ভগ্নাংশ`` without a heavy morphological analyzer.
2. ``expand_query`` — curated synonym/paraphrase expansion for common
   curriculum vocabulary (query side only; document text untouched).
3. ``trigram_cosine`` — character 3-gram cosine similarity used as a soft
   fallback signal when exact lexical overlap fails (spelling variants,
   loanword forms).

These are the dependency-free stand-ins for embedding-based dense retrieval;
the public contract (functions are pure, no network) is kept so a vector
backend can slot in behind the same interface later.
"""

import re
import unicodedata

# The character-class brackets are load-bearing. BAN-001 follow-up, measured
# 2026-10-17: written unbracketed (`r"\u0980-\u09FF"`), this pattern only
# matches the literal "U+0980-dash-U+09FF" sequence -- never a Bangla word --
# so light_stem returned every term unchanged and the stemmer was inert since
# its introduction. Bracketed, it is the Bangla-block membership test the
# suffix stripper needs.
_BANGLA_WORD_RE = re.compile("[A-Za-z0-9" + chr(92) + "u0980-" + chr(92) + "u09FF]+")
_BANGLA_RE = re.compile("[" + chr(92) + "u0980-" + chr(92) + "u09FF]")


#: Canonical digit form for matching: Bengali digits fold to ASCII so that
#: "১২৩" and "123" tokenize identically (AUD-A1-12). Applied inside
#: :func:`tokenize`, i.e. to BOTH the indexed corpus and every query, which
#: is what makes the equivalence hold on both sides; the stored/served text
#: keeps the digits exactly as the source published them.
_DIGIT_FOLD = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")

#: A4-04: unit normalization in the retrieval tokenizer. Measurement units
#: appear in student questions as English abbreviations ("3 km"), English
#: words ("kilometre"), Bangla abbreviations ("কিমি") or the full Bangla
#: term ("কিলোমিটার") — while the NCTB corpus prints the full Bangla form.
#: Every alias folds to the canonical corpus form, exact-token only (a
#: single-letter alias never folds inside a word), applied to BOTH the
#: indexed corpus and every query like the digit fold, so the equivalence
#: is symmetric. Deliberately small and curriculum-shaped: units the
#: class 6-10 science/maths syllabus measures with, nothing else.
UNIT_ALIASES: dict[str, str] = {
    # length
    "km": "কিলোমিটার",
    "kms": "কিলোমিটার",
    "kilometre": "কিলোমিটার",
    "kilometer": "কিলোমিটার",
    "কিমি": "কিলোমিটার",
    "m": "মিটার",
    "metre": "মিটার",
    "meter": "মিটার",
    "cm": "সেন্টিমিটার",
    "centimetre": "সেন্টিমিটার",
    "centimeter": "সেন্টিমিটার",
    "সেমি": "সেন্টিমিটার",
    # mass
    "kg": "কিলোগ্রাম",
    "kgs": "কিলোগ্রাম",
    "kilogram": "কিলোগ্রাম",
    "kilograms": "কিলোগ্রাম",
    "কেজি": "কিলোগ্রাম",
    "g": "গ্রাম",
    "gm": "গ্রাম",
    "gram": "গ্রাম",
    "grams": "গ্রাম",
    # volume
    "l": "লিটার",
    "litre": "লিটার",
    "liter": "লিটার",
    "litres": "লিটার",
    "liters": "লিটার",
    # time
    # (no bare "s": English possessives like "tomorrow's" tokenize to "s" and
    # would fold every such token to সেকেন্ড -- the wave-4 red-team contract
    # caught exactly that collision. "sec"/"secs" carry the unit meaning.)
    "sec": "সেকেন্ড",
    "secs": "সেকেন্ড",
    "second": "সেকেন্ড",
    "seconds": "সেকেন্ড",
    "min": "মিনিট",
    "mins": "মিনিট",
    "minute": "মিনিট",
    "minutes": "মিনিট",
    "hr": "ঘণ্টা",
    "hrs": "ঘণ্টা",
    "hour": "ঘণ্টা",
    "hours": "ঘণ্টা",
    "ঘন্টা": "ঘণ্টা",
}


def tokenize(text: str) -> list[str]:
    """Tokenize keeping Bangla graphemes intact.

    ``\\w+\\`` splits on Bangla combining marks (vowel signs
    U+09BE-U+09CC, virama U+09CD), destroying words like 'বিশ্বকাপ'. The
    explicit range U+0980-U+09FF covers the full Bangla block incl. signs
    and digits.

    NFKC folds compatibility variants (e.g. mobile-keyboard precomposed vs
    decomposed Bangla) so indexing and querying stay symmetric, Bengali
    digits fold to ASCII so "১২৩" and "123" are the same token (AUD-A1-12),
    and unit spellings fold to one canonical form so "৩ km", "৩ কিমি" and
    "৩ কিলোমিটার" retrieve the same passages (A4-04/A2-03). All three folds
    apply to BOTH the indexed corpus and every query -- the functions that
    read one side always read the other through the same tokenizer. Lives
    beside :func:`light_stem` rather than in :mod:`bm25` because both the
    lexical index and the query-side analysis need it, and the analysis
    layer must not depend on the index.
    """
    return [
        UNIT_ALIASES.get(token := match.group(0).lower().translate(_DIGIT_FOLD), token)
        for match in _BANGLA_WORD_RE.finditer(unicodedata.normalize("NFKC", text))
    ]


# Longest-match-first so 'গুলোকে' wins over 'কে'.
_SUFFIXES: tuple[str, ...] = (
    "গুলোকে",
    "গুলোতে",
    "গুলোর",
    "গুলো",
    "গুলিতে",
    "গুলির",
    "গুলি",
    "টিকে",
    "টির",
    "টার",
    "টি",
    "টা",
    "দের",
    "য়ের",
    "ের",
    "তে",
    "কে",
)

_MIN_STEM_LEN = 3

#: Curated query-side expansion map. Keys are stemmed terms; values add
#: related corpus vocabulary so paraphrased student questions retrieve.
QUERY_EXPANSIONS: dict[str, frozenset[str]] = {
    "সালোকসংশ্লেষণ": frozenset({"খাদ্য", "ক্লোরোফিল", "উদ্ভিদ", "সূর্য"}),
    "গাছ": frozenset({"উদ্ভিদ"}),
    "উদ্ভিদ": frozenset({"গাছ"}),
    "পাতা": frozenset({"ক্লোরোফিল", "শিরা"}),
    "আলো": frozenset({"প্রতিফলন", "প্রতিসরণ", "দর্পণ"}),
    "বিদ্যুৎ": frozenset({"প্রবাহ", "রোধ", "ওহম"}),
    "কোষ": frozenset({"নিউক্লিয়াস", "সাইটোপ্লাজম", "টিস্যু"}),
    "ভগ্নাংশ": frozenset({"লব", "হর"}),
    "সংখ্যা": frozenset({"মৌলিক", "পূর্ণসংখ্যা"}),
    "কোণ": frozenset({"সমকোণ", "সূক্ষ্মকোণ", "স্থূলকোণ"}),
    "ত্রিভুজ": frozenset({"অতিভুজ", "লম্ব", "ভূমি", "পিথাগোরাস"}),
    # হাইপা is the colloquial abbreviation of অতিভুজ — a root *change*, so it
    # belongs here (curated expansion) and not in the spell-checker, whose
    # first-grapheme rule excludes it by design.
    "হাইপা": frozenset({"অতিভুজ", "ত্রিভুজ"}),
    "আয়না": frozenset({"প্রতিবিম্ব", "প্রতিফলন"}),
    "লোহা": frozenset({"চুম্বক", "আকর্ষণ"}),
    "বৃত্ত": frozenset({"পরিধি", "ব্যাসার্ধ", "ক্ষেত্রফল"}),
    "এনজাইম": frozenset({"ভিত", "প্রভাবক"}),
    "শ্বসন": frozenset({"অক্সিজেন", "শক্তি", "ফুসফুস"}),
    "চুম্বক": frozenset({"মেরু", "আকর্ষণ"}),
    "তাপ": frozenset({"তাপমাত্রা", "পরিবহন", "পরিচলন"}),
}


def light_stem(term: str) -> str:
    """Strip one common inflectional suffix; never shorten a term below
    ``_MIN_STEM_LEN`` (3) characters."""
    if not _BANGLA_RE.search(term):
        return term
    for suffix in _SUFFIXES:
        if term.endswith(suffix) and len(term) - len(suffix) >= _MIN_STEM_LEN:
            return term[: len(term) - len(suffix)]
    return term


def expand_query(terms: list[str], extra: list[str] | None = None) -> list[str]:
    """Return the original terms plus curated expansions (deduplicated).

    ``extra`` carries corpus-vocabulary expansions computed by the caller
    (the spelling and Banglish lanes in :class:`BM25Index`); they are added
    after the curated map so an observed corpus term can never be displaced
    by a dictionary suggestion.
    """
    out = list(dict.fromkeys(terms))
    for term in terms:
        stemmed = light_stem(term)
        expansion = QUERY_EXPANSIONS.get(stemmed)
        if expansion:
            out.extend(t for t in expansion if t not in out)
    for term in extra or []:
        if term and term not in out:
            out.append(term)
    return out


def trigram_ngrams(text: str) -> frozenset[str]:
    """Character-trigram set of a text, for precomputing at index build."""
    compact = re.sub(r"\s+", "", text.lower())
    return frozenset(compact[i : i + 3] for i in range(max(len(compact) - 2, 0)))


def trigram_jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    """Jaccard similarity of two precomputed trigram sets, in [0, 1]."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def trigram_similarity(a: str, b: str) -> float:
    """Character-trigram Jaccard-style similarity in [0, 1]."""
    return trigram_jaccard(trigram_ngrams(a), trigram_ngrams(b))
