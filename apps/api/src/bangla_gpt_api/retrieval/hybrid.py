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

from bangla_gpt_api.retrieval.normalize import normalize_nfkc

# The character-class brackets are load-bearing. BAN-001 follow-up, measured
# 2026-10-17: written unbracketed (`r"\u0980-\u09FF"`), this pattern only
# matches the literal "U+0980-dash-U+09FF" sequence -- never a Bangla word --
# so light_stem returned every term unchanged and the stemmer was inert since
# its introduction. Bracketed, it is the Bangla-block membership test the
# suffix stripper needs.
_BANGLA_WORD_RE = re.compile("[A-Za-z0-9" + chr(92) + "u0980-" + chr(92) + "u09FF]+")
_BANGLA_RE = re.compile("[" + chr(92) + "u0980-" + chr(92) + "u09FF]")


def tokenize(text: str) -> list[str]:
    """Tokenize keeping Bangla graphemes intact.

    ``\\w+\\`` splits on Bangla combining marks (vowel signs
    U+09BE-U+09CC, virama U+09CD), destroying words like 'বিশ্বকাপ'. The
    explicit range U+0980-U+09FF covers the full Bangla block incl. signs
    and digits.

    The shared normalizer (retrieval/normalize.py) folds compatibility
    variants (mobile-keyboard precomposed vs decomposed Bangla) and strips
    zero-width inserts, so indexing and querying stay symmetric. Lives
    beside :func:`light_stem` rather than in :mod:`bm25` because both the
    lexical index and the query-side analysis need it, and the analysis
    layer must not depend on the index.
    """
    return [match.group(0).lower() for match in _BANGLA_WORD_RE.finditer(normalize_nfkc(text))]


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


def _normalized_for_ngrams(text: str) -> str:
    """The shared normalization, applied before whitespace folding.

    The trigram lane used to gram the raw string while the corpus side was
    ingested normalized: ``য়`` typed precomposed or decomposed, or a word
    carrying a ZWNJ/ZWJ from an IME or a PDF copy-paste, produced different
    trigram sets for the same word and therefore different hits and ranking
    at ``/search`` (F-104). Normalizing here is idempotent for text that is
    already normalized, which is what the index stores.
    """
    return re.sub(r"\s+", "", normalize_nfkc(text).lower())


def trigram_ngrams(text: str) -> frozenset[str]:
    """Character-trigram set of a text, for precomputing at index build."""
    compact = _normalized_for_ngrams(text)
    return frozenset(compact[i : i + 3] for i in range(max(len(compact) - 2, 0)))


def trigram_jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    """Jaccard similarity of two precomputed trigram sets, in [0, 1]."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def trigram_similarity(a: str, b: str) -> float:
    """Character-trigram Jaccard-style similarity in [0, 1]."""
    return trigram_jaccard(trigram_ngrams(a), trigram_ngrams(b))
