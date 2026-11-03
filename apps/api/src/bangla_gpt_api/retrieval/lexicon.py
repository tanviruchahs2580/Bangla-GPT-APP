"""The curated Bangla-language lexicons, in one versioned place.

The query-understanding maps used to live in two modules with no shared
ownership, version or drift test (audit F-12): curated expansions in
``retrieval/hybrid.py`` and the English→Bangla concept glossary in
``retrieval/query_analysis.py``. Both are *curation*: neither is learned,
both are auditable, and both are load-bearing for grounding (an expansion
that names a term the corpus never carries manufactures evidence).

Rules an editor must keep (pinned by ``tests/test_lexicon.py``):

* keys and values are single tokens, lowercase, no whitespace — retrieve
  tokens, not phrases;
* concept bridges point OUT of the student's script into the corpus
  script: expansions map a stemmed Bangla term to related Bangla corpus
  terms, glossary maps an English/Banglish token to Bangla curriculum
  terms; a map entry that points back at itself does nothing;
* every value must still be able to pass ``light_stem`` matching — use the
  surface form the syllabus actually prints, inflections cost nothing.

``LEXICON_VERSION`` moves (semver-style) whenever the contents change so an
ops incident can pin "which lexicon served that refusal".
"""

from __future__ import annotations

LEXICON_VERSION = "2026.11-rag-audit-b6"

# --- curated query-side expansion (Bangla → Bangla corpus terms) ------------
# Keys are STEMMED terms; values add related corpus vocabulary so
# paraphrased student questions retrieve. Consumed by retrieval.hybrid.
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

# --- English/Banglish → Bangla curriculum glossary (query side) --------------
# Code-switched questions name curriculum concepts in English ("what is
# cell?") while the textbook evidence is Bangla. Confined to terms the NCTB
# class 6–10 + HSC syllabus actually uses — a general dictionary would
# translate outside the corpus and manufacture coverage. Consumed by
# retrieval.query_analysis.
ENGLISH_BANGLA_GLOSSARY: dict[str, frozenset[str]] = {
    "cell": frozenset({"কোষ"}),
    "tissue": frozenset({"টিস্যু", "কোষ"}),
    "nucleus": frozenset({"নিউক্লিয়াস", "কোষ"}),
    "diffusion": frozenset({"ব্যাপন"}),
    "osmosis": frozenset({"অভিস্রবণ"}),
    "photosynthesis": frozenset({"সালোকসংশ্লেষণ", "সালোকসংশ্লেষ"}),
    "chlorophyll": frozenset({"ক্লোরোফিল", "পাতা"}),
    "respiration": frozenset({"শ্বসন"}),
    "enzyme": frozenset({"এনজাইম", "প্রভাবক"}),
    "heredity": frozenset({"বংশগতি"}),
    "chromosome": frozenset({"ক্রোমোজোম", "বংশগতি"}),
    "plant": frozenset({"উদ্ভিদ", "গাছ"}),
    "leaf": frozenset({"পাতা"}),
    "root": frozenset({"শিকড়"}),
    "seed": frozenset({"বীজ"}),
    "flower": frozenset({"ফুল"}),
    "water": frozenset({"পানি", "জল"}),
    "air": frozenset({"বাতাস"}),
    "oxygen": frozenset({"অক্সিজেন"}),
    "light": frozenset({"আলো"}),
    "mirror": frozenset({"আয়না", "প্রতিবিম্ব"}),
    "reflection": frozenset({"প্রতিফলন", "আয়না"}),
    "refraction": frozenset({"প্রতিসরণ"}),
    "lens": frozenset({"লেন্স"}),
    "shadow": frozenset({"ছায়া"}),
    "heat": frozenset({"তাপ", "তাপমাত্রা"}),
    "temperature": frozenset({"তাপমাত্রা"}),
    "magnet": frozenset({"চুম্বক", "মেরু"}),
    "electricity": frozenset({"বিদ্যুৎ", "প্রবাহ"}),
    "current": frozenset({"প্রবাহ", "বিদ্যুৎ"}),
    "circuit": frozenset({"বর্তনী"}),
    "resistance": frozenset({"রোধ"}),
    "force": frozenset({"বল"}),
    "motion": frozenset({"গতি"}),
    "energy": frozenset({"শক্তি"}),
    "work": frozenset({"কাজ", "শক্তি"}),
    "power": frozenset({"ক্ষমতা", "কাজ"}),
    "pressure": frozenset({"চাপ"}),
    "fraction": frozenset({"ভগ্নাংশ", "লব", "হর"}),
    "numerator": frozenset({"লব", "ভগ্নাংশ"}),
    "denominator": frozenset({"হর", "ভগ্নাংশ"}),
    "prime": frozenset({"মৌলিক", "সংখ্যা"}),
    "percentage": frozenset({"শতকরা"}),
    "ratio": frozenset({"অনুপাত", "সমানুপাত"}),
    # The former phrase values ('বীজগণিতীয় রাশি', 'বৃত্তের ক্ষেত্রফল') could
    # never match a single indexed token — the lexicon validator now rejects
    # phrases, so these keep the per-token curriculum terms instead.
    "algebra": frozenset({"বীজগণিত", "রাশি"}),
    "equation": frozenset({"সমীকরণ"}),
    "variable": frozenset({"চলক", "রাশি"}),
    "triangle": frozenset({"ত্রিভুজ"}),
    "hypotenuse": frozenset({"অতিভুজ", "ত্রিভুজ"}),
    "circle": frozenset({"বৃত্ত", "ক্ষেত্রফল"}),
    "radius": frozenset({"ব্যাসার্ধ", "বৃত্ত"}),
    "diameter": frozenset({"ব্যাস", "বৃত্ত"}),
    "perimeter": frozenset({"পরিধি"}),
    "area": frozenset({"ক্ষেত্রফল"}),
    "number": frozenset({"সংখ্যা"}),
    "integer": frozenset({"পূর্ণসংখ্যা"}),
    "square": frozenset({"বর্গ", "বর্গাকার"}),
    "cube": frozenset({"ঘন", "ঘনফল"}),
    "profit": frozenset({"লাভ"}),
    "loss": frozenset({"ক্ষতি"}),
    "interest": frozenset({"সুদ"}),
    "average": frozenset({"গড়"}),
    "speed": frozenset({"দ্রুতি", "গতি"}),
    "exponent": frozenset({"সূচক"}),
    "index": frozenset({"সূচক"}),
    "gravity": frozenset({"মহাকর্ষ", "অভিকর্ষ"}),
    "sound": frozenset({"শব্দ"}),
    "wave": frozenset({"তরঙ্গ"}),
    "atom": frozenset({"পরমাণু"}),
    "molecule": frozenset({"অণু"}),
    "acid": frozenset({"অ্যাসিড"}),
    "base": frozenset({"ক্ষারক"}),
    "salt": frozenset({"লবণ"}),
    "digestion": frozenset({"পরিপাক"}),
    "blood": frozenset({"রক্ত"}),
    "heart": frozenset({"হৃদপিণ্ড"}),
    "virus": frozenset({"ভাইরাস"}),
    "bacteria": frozenset({"ব্যাকটেরিয়া"}),
    "wifi": frozenset({"ওয়াইফাই", "বেতার"}),
    "computer": frozenset({"কম্পিউটার"}),
    "internet": frozenset({"ইন্টারনেট"}),
}


def validate_lexicon() -> list[str]:
    """Curation defects that would silently corrupt grounding.

    Returns a list of human-readable problems; empty means the lexicon is
    internally consistent. Scripts and pinning tests import this instead of
    re-implementing the rules, so a new editor cannot fork the contract.
    """
    problems: list[str] = []
    _is_latin = str.isascii

    maps = {
        "QUERY_EXPANSIONS": QUERY_EXPANSIONS,
        "ENGLISH_BANGLA_GLOSSARY": ENGLISH_BANGLA_GLOSSARY,
    }
    for map_name, mapping in maps.items():
        for key, values in mapping.items():
            if not key or " " in key or key != key.strip().lower():
                problems.append(f"{map_name}[{key!r}]: keys must be single lowercase tokens")
            if not values:
                problems.append(f"{map_name}[{key!r}]: maps to nothing (dead curation)")
            for value in values:
                if " " in value:
                    problems.append(f"{map_name}[{key!r}]: phrase {value!r} — tokens only")
                if value == key:
                    problems.append(f"{map_name}[{key!r}]: self-referential entry does nothing")

    for key in ENGLISH_BANGLA_GLOSSARY:
        if not _is_latin(key):
            problems.append(f"glossary key {key!r} must be the English/Banglish surface form")
    for key in QUERY_EXPANSIONS:
        if _is_latin(key):
            problems.append(f"expansion key {key!r} must be the Bangla (stemmed) term")
    return problems
