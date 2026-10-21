"""Query-side linguistic analysis: what in a question must the evidence cover?

The grounding gate (``TutorService._gate``) used to treat every query token as
equally important. Measured on the live deployment (2026-10-17 RAG review):
``"সালোকসংশ্লেষণ কী এবং কোথায় ঘটে?"`` — a question about a section that
*exists in the served corpus* — was refused at coverage 0.40, because three of
its five tokens were ``এবং`` / ``কোথায়`` / ``ঘটে``: conjunction, locative and
verb forms no textbook passage can ever "cover". The one content term the
question carried was covered.

This module is the fix, split into the pieces that are independently true:

* :data:`BANGLA_STOP_WORDS` — function words (copulas, conjunctions, question
  particles, pronouns, postpositions). Stop-words are *removed from coverage
  accounting only*: they still participate in BM25 retrieval, where their
  document frequency does the ranking work that raw coverage cannot.
* :data:`ROMAN_STOP_WORDS` — the same words in the romanisation students
  actually type (``ki``, ``kothay``, ``kivabe`` …): Banglish queries must not
  fail for script reasons alone.
* :func:`content_terms` — stemmed, stop-word-filtered query terms; the set
  every downstream signal is computed over.
* :func:`coverage_weigths` — per-term weight from corpus document frequency
  (``ln(1 + N/df)``). A term that appears in every textbook chunk cannot
  carry the gate; a term that appears in one can. When no statistics are
  available the weight is 1 for content terms, so a caller without stats
  degrades to the stop-word behaviour, never to a lie.

Everything here is deterministic and pure: no network, no model, no state.
"""

from __future__ import annotations

import math
from collections.abc import Iterable

from bangla_gpt_api.retrieval.hybrid import light_stem, tokenize

# --- stop-words ---------------------------------------------------------------
#
# Curated by inflection family, not by frequency count — a frequency-derived
# list silently absorbs content words of a small corpus (on 78 sample chunks
# "কোষ" is among the most frequent tokens in the book; it must never be a
# stop-word). Every entry is a function word in Bangla grammar: copulas,
# conjuctions, postpositions, pronouns, interrogatives and question
# particles. Stored UNSTEMMED: the gate stems query terms before lookup, and
# stemming "হয়েছে" must not have to reach the list as "হয়".

BANGLA_STOP_WORDS: frozenset[str] = frozenset(
    {
        # copulas and auxiliaries
        "হয়",
        "হয়েছে",
        "হয়ে",
        "হল",
        "হলো",
        "হত",
        "হবে",
        "হচ্ছে",
        "ছিল",
        "ছিলেন",
        "আছে",
        "আছেন",
        "করে",
        "করা",
        "করি",
        "করেন",
        "করেছে",
        "দেয়",
        "পাওয়া",
        "থাকে",
        "থাকা",
        "থেকে",
        # conjunctions / particles
        "এবং",
        "ও",
        "কিন্তু",
        "অথবা",
        "বা",
        "যে",
        "যা",
        "যেখানে",
        "যখন",
        "তখন",
        "তাই",
        "অর্থাৎ",
        "মানে",
        "না",
        "নেই",
        "জানতে",
        # pronouns
        "আমি",
        "আমার",
        "তুমি",
        "তোমার",
        "আপনি",
        "সে",
        "তার",
        "তাদের",
        "এটা",
        "এটি",
        "ওটা",
        "ওটি",
        "কেউ",
        "কোনো",
        # interrogatives / question particles
        "কী",
        "কি",
        "কোথায়",
        "কেন",
        "কিভাবে",
        "কীভাবে",
        "কত",
        "কতটুকু",
        "কবে",
        "কোন",
        "কাকে",
        "কার",
        # postpositions / very common determiners
        "এর",
        "একটি",
        "একটা",
        "এক",
        "দুটি",
        "সব",
        "সমস্ত",
        "মধ্যে",
        "উপর",
        "উপরে",
        "নিচে",
        "ভিতরে",
        "বাইরে",
        "সাথে",
        "জন্য",
        "অনেক",
        "বেশি",
        "কম",
        "এখন",
        "পরে",
        "আবার",
        # A8-08 (2026-10-21): postpositions, pronouns and the highest-frequency
        # verb/auxiliary forms. The list already carried "থাকে", "করে",
        # "দেয়", "হয়", "হলো"; these are the same class and were the tokens
        # that made golden-set windows read as fragments ("নেই বিন্দু কী?",
        # "থাকলে হলো কী?", "আয়তন বের কী?"). They are function words in
        # coverage terms: the evidence can neither contain the student's verb
        # frame nor be expected to restate it.
        "দিয়ে",
        "নিয়ে",
        "তাকে",
        "তারা",
        "এদের",
        "এসব",
        "যায়",
        "যেতে",
        "বলে",
        "করলে",
        "করতে",
        "থাকলে",
        "হলে",
        "নেওয়া",
        "আসে",
        "আসতে",
        "রাখা",
        "রাখতে",
        "বের",
        "দেখতে",
        "দেখা",
        "লিখতে",
        "হিসেবে",
        "মতো",
        "পর্যন্ত",
    }
)

#: The same function words in the romanisation students type. Keeping this list
#: separate from :data:`BANGLA_STOP_WORDS` documents that Banglish is treated
#: as its own surface form: ``ki`` and ``কী`` arrive through different code
#: paths and both must vanish from coverage accounting.
ROMANISED_STOP_WORDS: frozenset[str] = frozenset(
    {
        "ki",
        "kothay",
        "kivabe",
        "keno",
        "koto",
        "kon",
        "kake",
        "karon",
        "hoy",
        "hobe",
        "hoilo",
        "hose",
        "chilo",
        "ache",
        "thake",
        "theka",
        "kore",
        "kora",
        "kori",
        "koren",
        "dey",
        "na",
        "nei",
        "ebong",
        "o",
        "kintu",
        "othoba",
        "ba",
        "je",
        "ja",
        "jemon",
        "mani",
        "ami",
        "amar",
        "tumi",
        "tomar",
        "apni",
        "she",
        "tar",
        "tader",
        "eta",
        "oti",
        "ekta",
        "ek",
        "duti",
        "sob",
        "shob",
        "moddhe",
        "upore",
        "niche",
        "sathe",
        "jonno",
        "jonnyo",
        "onek",
        "beshi",
        "kom",
        "ekhon",
        "pore",
        "abar",
        "theke",
    }
)

#: English function words that ride along in code-switched questions (``what is
#: cell``). Deliberately tiny: it exists so an English question frame does not
#: drown the one content word a Banglish question carries.
ENGLISH_STOP_WORDS: frozenset[str] = frozenset(
    {
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "be",
        "of",
        "in",
        "on",
        "at",
        "to",
        "and",
        "or",
        "what",
        "which",
        "how",
        "why",
        "where",
        "when",
        "who",
        "do",
        "does",
        "did",
        "can",
        "it",
        "its",
        "by",
        "for",
        "with",
        "tell",
        "me",
        "please",
        "explain",
        "about",
    }
)

ALL_STOP_WORDS: frozenset[str] = BANGLA_STOP_WORDS | ROMANISED_STOP_WORDS | ENGLISH_STOP_WORDS

# --- question-framing words (second stop-word plane) --------------------------
#
# Distinct from the stop-words above: these are not filler, they are the
# student's *instruction frame* -- imperatives aimed at the tutor ("explain
# করো", "বুঝিয়ে বলো"), politeness, and the class/level context words of a
# school question ("৬ষ্ঠ শ্রেণির"). They must not count for or against
# grounding: the evidence can neither contain "করো" nor be expected to
# restate the grade the API parameter already carries. Kept on its own plane
# so the content stop-word list stays purely linguistic.
QUESTION_FRAMING_WORDS: frozenset[str] = frozenset(
    {
        # imperatives aimed at the tutor (BN + roman + EN pairings)
        "করো",
        "করুন",
        "কর",
        "বলো",
        "বলুন",
        "লিখো",
        "লিখুন",
        "লিখ",
        "বুঝিয়ে",
        "ব্যাখ্যা",
        "দাও",
        "দিন",
        "জানতে",
        "চাই",
        "explain",
        # cloze-question instruction frame (the quiz generator composes
        # "শূন্যস্থানে সঠিক শব্দটি বসান: {cloze}" — the scaffold is quiz
        # formatting, and its terms must not gate the referenced content)
        "শূন্যস্থানে",
        "বসান",
        # class/level context
        "শ্রেণি",
        "শ্রেণির",
        "ষষ্ঠ",
        "সপ্তম",
        "অষ্টম",
        "নবম",
        "দশম",
        "একাদশ",
        "দ্বাদশ",
        "ক্লাস",
        "অধ্যায়",
        # A8-08 (2026-10-21): the "what is meant by" frame. "প্রান্তের বিভব
        # বলতে কী বোঝায়?" asks for an explanation exactly as "ব্যাখ্যা করো"
        # does, and the words that carry the asking are not subject matter --
        # the textbook cannot be expected to contain them. Measured while
        # repairing the golden set's contextual stratum: its windows had paired
        # these with topic terms and produced fragments the live model refused
        # ("চাপ দুই কী?", false-refusal rate 0.0718).
        "বলতে",
        "বোঝায়",
        "বোঝা",
        "বোঝানো",
        "বোঝাও",
        "জানতে হয়",
        # roman forms of the same
        "koro",
        "korun",
        "bolo",
        "bolun",
        "likho",
        "bujhiye",
        "byakha",
        "dao",
        "din",
        "jante",
        "chai",
        "bolte",
        "bojhay",
    }
)


def is_stop_word(term: str) -> bool:
    """True for function words in any script the app accepts."""
    return term in ALL_STOP_WORDS


def is_framing_term(term: str) -> bool:
    """True for instruction-frame and class/level context words.

    A framing term is neither filler nor subject matter: "ব্যাখ্যা করো" is
    an instruction to the tutor, "৬ষ্ঠ শ্রেণির" carries the level the API
    already supplies. Counting them in coverage lets the student's sentence
    frame dilute -- or, weighted at the IDF maximum, veto -- an otherwise
    answerable question.
    """
    return term in QUESTION_FRAMING_WORDS


def _is_numeric_token(token: str) -> bool:
    """True for tokens whose leading character is a digit in any script.

    "৬ষ্ঠ", "১ম", "8th" are grade framing, never textbook content.
    """
    return bool(token) and token[0] in "0123456789০১২৩৪৫৬৭৮৯"


def content_terms(text: str) -> tuple[str, ...]:
    """Stemmed, stop-word-filtered terms of ``text`` — the gate's terms.

    Order-preserving and de-duplicated: coverage is set arithmetic with
    weights, so duplicates would only double-count. Framing terms and
    grade-numeric tokens are removed at the same boundary.
    """
    seen: dict[str, None] = {}
    for token in tokenize(text.replace("____", " ")):
        if len(token) < 2:
            continue  # single-character Bangla vowel signs and stray digits
        if set(token) == {"_"}:
            continue  # cloze blank markers are formatting
        if _is_numeric_token(token):
            continue
        stemmed = light_stem(token)
        if (
            is_stop_word(stemmed)
            or is_stop_word(token)
            or is_framing_term(stemmed)
            or is_framing_term(token)
        ):
            continue
        seen.setdefault(stemmed, None)
    return tuple(seen)


def coverage_weights(
    terms: Iterable[str],
    document_frequency: dict[str, int],
    total_documents: int,
) -> dict[str, float]:
    """Per-term weight ``ln(1 + N/df)`` from corpus document frequencies.

    A rare curriculum term (``df`` small) weighs close to ``ln(N)``; a term in
    every chunk weighs close to ``ln(2)``. Miss-listing a ubiquitous term then
    costs the gate almost nothing, which is exactly right: evidence cannot be
    expected to restate the question's scaffolding. With an empty frequency
    map every term weighs 1 — the uniform fallback a caller without corpus
    statistics gets.
    """
    weights: dict[str, float] = {}
    for term in terms:
        if total_documents <= 0:
            weights[term] = 1.0
            continue
        df = document_frequency.get(term, 0)
        weights[term] = math.log(1.0 + (total_documents / df if df > 0 else total_documents))
    return weights


def weighted_coverage(
    terms: tuple[str, ...],
    covered: Iterable[str],
    weights: dict[str, float],
) -> float:
    """Weight of the covered terms over the weight of all terms, in [0, 1]."""
    total = sum(weights.get(t, 1.0) for t in terms)
    if total <= 0.0:
        return 0.0
    covered_terms = set(covered)
    covered_weight = sum(weights.get(t, 1.0) for t in terms if t in covered_terms)
    return min(covered_weight / total, 1.0)


# --- English → Bangla curriculum glossary (query side) ------------------------
#
# Code-switched questions name curriculum concepts in English ("what is
# cell?") while the textbook evidence is Bangla. This map is the query-side
# bridge: an English/Banglish token expands to its Bangla curriculum term(s)
# and retrieval proceeds unchanged. It is deliberately confined to the terms
# the NCTB class 6–10 + HSC syllabus actually uses — a general-purpose
# dictionary would translate outside the corpus and manufacture coverage.
# Entries are concepts, not every word: "what is" is handled by the
# stop-word lists above, not by translation.

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
    "algebra": frozenset({"বীজগণিতীয় রাশি", "বীজগণিত"}),
    "equation": frozenset({"সমীকরণ"}),
    "variable": frozenset({"চলক", "বীজগণিতীয় রাশি"}),
    "triangle": frozenset({"ত্রিভুজ"}),
    "hypotenuse": frozenset({"অতিভুজ", "ত্রিভুজ"}),
    "circle": frozenset({"বৃত্ত", "বৃত্তের ক্ষেত্রফল"}),
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


def english_gloss_terms(token: str) -> tuple[str, ...]:
    """Bangla curriculum terms an English/Banglish token glosses to.

    Lower-led, exact match: the glossary is a *concept* bridge, and fuzzy
    English → Bangla matching would silently invent coverage. An unmapped
    token (``fractal``, ``photosynthesis2``) expands to nothing, and the
    question is then answered — or refused — on everything else it carries.
    """
    return tuple(ENGLISH_BANGLA_GLOSSARY.get(token.strip().lower(), ()))
