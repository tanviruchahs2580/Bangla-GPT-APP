"""Hybrid-retrieval helpers over the lexical BM25 baseline.

Three recall boosters, all deterministic and dependency-free:

1. ``light_stem``      — conservative Bangla inflection stripper so that
   ``ভগ্নাংশের`` matches ``ভগ্নাংশ`` without a heavy morphological analyzer.
2. ``expand_query``    — curated synonym/paraphrase expansion for common
   curriculum vocabulary (query side only; document text untouched).
3. ``trigram_cosine``  — character 3-gram cosine similarity used as a soft
   fallback signal when exact lexical overlap fails (spelling variants,
   loanword forms).

These are the dependency-free stand-ins for embedding-based dense retrieval;
the public contract (functions are pure, no network) is kept so a vector
backend can slot in behind the same interface later.
"""

import re

_BANGLA_RE = re.compile(r"\u0980-\u09FF")

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
    "বৃত্ত": frozenset({"পরিধি", "ব্যাসার্ধ", "ক্ষেত্রফল"}),
    "এনজাইম": frozenset({"ভিত", "প্রভাবক"}),
    "শ্বসন": frozenset({"অক্সিজেন", "শক্তি", "ফুসফুস"}),
    "চুম্বক": frozenset({"মেরু", "আকর্ষণ"}),
    "তাপ": frozenset({"তাপমাত্রা", "পরিবহন", "পরিচলন"}),
}


def light_stem(term: str) -> str:
    """Strip one common inflectional suffix; never shorten below 4 chars."""
    if not _BANGLA_RE.search(term):
        return term
    for suffix in _SUFFIXES:
        if term.endswith(suffix) and len(term) - len(suffix) >= _MIN_STEM_LEN:
            return term[: len(term) - len(suffix)]
    return term


def expand_query(terms: list[str]) -> list[str]:
    """Return the original terms plus curated expansions (deduplicated)."""
    out = list(dict.fromkeys(terms))
    for term in terms:
        stemmed = light_stem(term)
        extra = QUERY_EXPANSIONS.get(stemmed)
        if extra:
            out.extend(t for t in extra if t not in out)
    return out


def _char_ngrams(text: str, n: int = 3) -> set[str]:
    compact = re.sub(r"\s+", "", text.lower())
    return {compact[i : i + n] for i in range(max(len(compact) - n + 1, 0))}


def trigram_similarity(a: str, b: str) -> float:
    """Character-trigram Jaccard-style similarity in [0, 1]."""
    ga, gb = _char_ngrams(a), _char_ngrams(b)
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / len(ga | gb)
