"""Child-safety moderation for a minors-focused tutoring platform.

Every student free-text question passes through ``screen_question`` before it
reaches retrieval or the LLM. Blocked categories get a supportive,
age-appropriate refusal — never an error page, never the raw pattern match.
The layer is intentionally keyword-regex based (deterministic, auditable,
zero-latency); an LLM-based classifier can complement it later.
"""

import re
from dataclasses import dataclass

SAFETY_ANSWER = "এই প্রশ্নের উত্তর এই প্ল্যাটফর্মে দেওয়া যাচ্ছে না। এটি আপনার জন্য ক্ষতিকর হতে পারে।"
SELF_HARM_ANSWER = (
    "আপনি নিজেকে কষ্ট দিতে চাইলে অনুগ্রহ করে কাছের কোনো বড় মানুষ, "
    "অভিভাবক বা শিক্ষককে সঙ্গে কথা বলুন। আপনি গুরুত্বপূর্ণ — সাহায্য পাওয়া সম্ভব। "
    "জাতীয় মানসিক স্বাস্থ্য সহায়তা: ০৯৬৬৬-৭৭৭২২২।"
)

# Category -> compiled regex over the normalized question text.
_PATTERNS: tuple[tuple[str, str], ...] = (
    # Self-harm / suicide ideation or method-seeking
    (
        "self_harm",
        r"আত্মহত্যা|আত্মঘাতী|নিজেকে\s*মার|গিলে\s*ফেল|বিষ\s*খাও|ফাঁসি\s*দেও|কাটা\s*যাবে",
    ),
    # Weapons / explosives synthesis
    ("weapon_synthesis", r"বোমা|বিস্ফোরক|অগ্নিসংযোগ|অস্ত্র\s*(বানা|তৈরি)|গুলি\s*চালানোর?\s*(উপায়|ভাব)"),
    # Illicit drug synthesis / acquisition
    ("drug_synthesis", r"মাদক|ইয়াবা|কোকেইন|হেরোইন|গাঁজা\s*(বানা|কেনা)|নেশা\s*(বানা|জাত)"),
    # Sexual content (esp. anything sexualizing minors)
    ("sexual_content", r"যৌন|কাম\s*কাণ্ড|শ্লীলতাহানি|ধর্ষণ|পর্ন|অশ্লীল\s*(ছবি|ভিডিও|গল্প)"),
    # Violence / gore seeking
    ("violence", r"মারধরের?\s*(ভিডিও|উপায়)|কে?\s*খুন\s*(কর|করা)|পিটুনি\s*দেওয়ার"),
    # Personal-data harvesting about third parties
    ("personal_data", r"(ঠিকানা|ফোন\s*নম্বর)\s*(দাও|দে\s*যাও|বের\s*কর)"),
)

_COMPILED: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (name, re.compile(pattern)) for name, pattern in _PATTERNS
)


@dataclass(frozen=True)
class SafetyVerdict:
    """Result of screening one user question."""

    safe: bool
    reason: str | None = None


# S4.8 age-appropriateness: the NCTB syllabus legitimately teaches
# reproduction -- the class-8 science chapter term for sexual reproduction
# (codepoints pinned: U+09AF U+09CC U+09A8 / U+09AA U+09CD U+09B0 U+099C U+09A8
# U+09A8) must not be blocked by the sexual_content keyword. Academic phrases
# are lifted out BEFORE the keyword runs, so the SAME keyword still fires for
# the word in any non-academic context.
_ACADEMIC_SCIENCE_TERMS: tuple[re.Pattern[str], ...] = (
    re.compile("\u09af\u09cc\u09a8\\s*\u09aa\u09cd\u09b0\u099c\u09a8\u09a8"),
)


def screen_question(question: str) -> SafetyVerdict:
    """Return a verdict for a free-text question (S4.8: academic-context aware)."""
    for name, pattern in _COMPILED:
        probe = question
        if name == "sexual_content":
            for academic in _ACADEMIC_SCIENCE_TERMS:
                probe = academic.sub(" ", probe)
        if pattern.search(probe):
            if name == "self_harm":
                return SafetyVerdict(safe=False, reason="self_harm")
            return SafetyVerdict(safe=False, reason=name)
    return SafetyVerdict(safe=True)


def refusal_for(reason: str) -> str:
    """Age-appropriate refusal copy per category."""
    if reason == "self_harm":
        return SELF_HARM_ANSWER
    return SAFETY_ANSWER


def verify_citation(answer: str, evidence_text: str) -> bool:
    """Heuristic post-generation check: does the answer lean on the evidence?

    Computes stem-level term coverage of the answer inside the retrieved
    evidence. A grounded answer that invents unrelated material scores low.
    This is a soft signal — callers log a warning rather than discard.
    """
    from bangla_gpt_api.retrieval.bm25 import tokenize
    from bangla_gpt_api.retrieval.hybrid import light_stem

    answer_terms = {light_stem(t) for t in tokenize(answer) if len(t) >= 3}
    if not answer_terms:
        return True
    evidence_terms = {light_stem(t) for t in tokenize(evidence_text)}
    coverage = sum(1 for t in answer_terms if t in evidence_terms) / len(answer_terms)
    return coverage >= 0.25


# ── S4.8: prompt-injection filter for corpus ingest ───────────────────────
# Textbook chunks are UNTRUSTED data too: a poisoned corpus document must
# never steer the model or extract the system prompt. Instruction-override and
# system-leak sentences are therefore removed at ingest time, before a chunk
# is ever built (deterministic, auditable, zero-latency -- same philosophy as
# screen_question). The runtime layer (<evidence> data-only rules + tag
# sanitizing) stays as the second line of defence.
_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    # English: instruction override / system-prompt exfiltration / tag spoof
    re.compile(
        r"ignore\s+(all\s+|the\s+)?(previous|prior|earlier|above)\s+(instructions?|rules?|prompts?)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(reveal|show|print|repeat|leak|output|display|say|write)\b[^.!?\n]{0,60}"
        r"\b(system|hidden|secret|original)\b[^.!?\n]{0,30}\b(prompt|instructions?|rules?)\b",
        re.IGNORECASE,
    ),
    re.compile(r"new\s+system\s+prompt", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+(in\s+)?[a-z]*\s*mode", re.IGNORECASE),
    re.compile(r"<\s*/?\s*(system|assistant|instructions?)\s*>", re.IGNORECASE),
    # Bengali: same intent, loanwords 'system'/'prompt' + leak verbs, and the
    # "forget the previous rules" override. Unicode-escape literals only (repo rule).
    re.compile(
        "\u09b8\u09bf\u09b8\u09cd\u099f\u09c7\u09ae"  # "system" (translit)
        "[^\u0964!?\\n]{0,40}"
        "(\u09aa\u09cd\u09b0\u09ae\u09cd\u09aa\u099f\u09c7"  # prompt-acc
        "|\u09a8\u09bf(?:\u09b0\u09cd|\u09a8\u09cd)?\u09a6\u09c7\u09b6"  # nirdesh/nindesh
        "|\u09a8\u09bf[\u09af\u09df]\u09bc?\u09ae"  # niyom (plain ya or nukta-ya)
        "|\u09aa\u09cd\u09b0\u0995\u09be\u09b6"  # publish/reveal
        "|\u09ab\u09be\u0981\u09b8)"  # leak
    ),
    re.compile(
        "(\u09aa\u09cd\u09b0\u09ae\u09cd\u09aa\u099f\u0995|\u09aa\u09cd\u09b0\u09ae\u09cd\u09aa\u099f\u09c7"
        "|\u09b8\u09bf\u09b8\u09cd\u099f\u09c7\u09ae)[^\u0964!?\\n]{0,30}"
        "(\u09a6\u09c7\u0996\u09be\u0993|\u09ac\u09b2\u09cb|\u09a6\u09be\u0993"
        "|\u09b2\u09bf\u0996\u09cb|\u09aa\u09cd\u09b0\u0995\u09be\u09b6"
        "|\u09ab\u09be\u0981\u09b8|\u09ac\u09be\u09b9\u09bf\u09b0)"
    ),
    re.compile(
        "(\u0986\u0997\u09c7\u09b0|\u0986\u0997\u09c7\u0995\u09be\u09b0"
        "|\u09aa\u09c2\u09b0\u09cd\u09ac\u09c7\u09b0|\u0989\u09aa\u09b0\u09c7\u09b0)"
        "[^\u0964!?\\n]{0,25}"
        "(\u09a8\u09bf[\u09af\u09df]\u09bc?\u09ae|\u09a8\u09bf(?:\u09b0\u09cd|\u09a8\u09cd)?\u09a6\u09c7\u09b6)"
        "[^\u0964!?\\n]{0,25}"
        "(\u09ad\u09c1\u09b2\u09c7|\u0989\u09aa\u09c7\u0995\u09cd\u09b7\u09be"
        "|\u09ae\u09c1\u099b\u09c7|\u09ae\u09be\u09a8\u09cb \u09a8\u09be)"
    ),
    re.compile(
        "(\u09a8\u09a4\u09c1\u09a8|\u09a8\u09a4\u09c1\u09a8)\\s*"
        "(\u09b8\u09bf\u09b8\u09cd\u099f\u09c7\u09ae\\s*)?"
        "(\u09a8\u09bf\u09df\u09ae|\u09a8\u09bf\u09b0\u09cd\u09a6\u09c7\u09b6"
        "|\u09aa\u09cd\u09b0\u09ae\u09cd\u09aa\u099f)"
    ),
)
_SENT_SPLIT_KEEP = re.compile("([^\u0964.!?]+[\u0964.!?]?)")


def strip_injections(text: str) -> tuple[str, int]:
    """Remove instruction-override/leak sentences; return (clean_text, dropped).

    Clean text is returned byte-for-byte untouched (drop count 0) so an
    unpoisoned corpus chunk hash/text never changes.
    """
    parts = [p for p in _SENT_SPLIT_KEEP.findall(text) if p.strip()]
    kept = [p for p in parts if not any(rx.search(p) for rx in _INJECTION_PATTERNS)]
    removed = len(parts) - len(kept)
    if removed == 0:
        return text, 0
    return " ".join(p.strip() for p in kept), removed


# ── S4.8: age-appropriateness clause shared BYTE-IDENTICAL by all four
# system prompts (tutor + content/lesson/question-paper generators, R5).
AGE_RULE_SENTENCE = (
    "\u09b6\u09bf\u0995\u09cd\u09b7\u09be\u09b0\u09cd\u09a5\u09c0\u09b0\u09be "
    "\u0995\u09bf\u09b6\u09cb\u09b0-\u0995\u09bf\u09b6\u09cb\u09b0\u09c0: "
    "\u09aa\u09cd\u09b0\u09a4\u09bf\u099f\u09bf\u099f\u09cb \u0989\u09a4\u09cd\u09a4\u09b0 "
    "\u09ac\u09df\u09b8\u09cb\u09aa\u09af\u09cb\u0997\u09c0, \u09b6\u09be\u09b2\u09c0\u09a8 "
    "\u0993 \u09b6\u09c1\u09a7\u09c1 \u09b6\u09bf\u0995\u09cd\u09b7\u09be\u09ae\u09c2\u09b2\u0995 "
    "\u09aa\u09cd\u09b0\u09b8\u0999\u09cd\u0997\u09c7\u0987 \u09b0\u09be\u0996\u09cb\u0964 "
    "\u09aa\u09be\u09a0\u09cd\u09af\u0995\u09cd\u09b0\u09ae\u09c7\u09b0 "
    "\u09ac\u09bf\u099c\u09cd\u099e\u09be\u09a8 "
    "\u09aa\u09b0\u09bf\u09ad\u09be\u09b7\u09be (\u09af\u09c7\u09ae\u09a6 "
    "\u09af\u09cc\u09a8 \u09aa\u09cd\u09b0\u099c\u09a8\u09a8) "
    "\u098f\u0995\u09be\u09a1\u09c7\u09ae\u09bf\u0995 "
    "\u09ad\u09be\u09b7\u09be\u09a4\u09c7\u0987 \u09ac\u09cd\u09af\u09be\u0996\u09cd\u09af\u09be "
    "\u0995\u09b0\u09cb; \u0985\u09b6\u09cd\u09b2\u09c0\u09b2, "
    "\u09b9\u09c1\u09ae\u0995\u09bf\u09ae\u09c2\u09b2\u0995 "
    "\u09ac\u09be \u09b6\u09bf\u09b6\u09c1\u09a6\u09c7\u09b0 \u099c\u09a8\u09cd\u09af "
    "\u0985\u0989\u09aa\u09af\u09c1\u0995\u09cd\u09a4 \u0995\u09cb\u09a8\u09cb "
    "\u09ac\u09b0\u09cd\u09a3\u09a8\u09be \u0995\u0996\u09a8\u09cb \u09a6\u09c7\u09ac\u09c7 "
    "\u09a8\u09be\u0964 "
    "\u09a8\u09bf\u099c\u09c7\u09b0 \u09a8\u09bf\u09b0\u09cd\u09a6\u09c7\u09b6\u09a8\u09be "
    "\u09ac\u09be \u09b8\u09bf\u09b8\u09cd\u099f\u09c7\u09ae "
    "\u09aa\u09cd\u09b0\u09ae\u09cd\u09aa\u099f\u09c7\u09b0 \u0995\u09a5\u09be\u0993 "
    "\u0995\u0996\u09a8\u09cb \u09aa\u09cd\u09b0\u0995\u09be\u09b6 \u0995\u09b0\u09ac\u09c7 "
    "\u09a8\u09be\u0964"
)


def answer_confidence(
    grounded: bool | None,
    refused_reason: str | None,
    scores: list[float],
) -> float | None:
    """Wave 2: honest numeric confidence for a tutoring answer.

    0.0 for refusals; None when there is no evidence signal at all;
    otherwise 0.5*breadth (source count, 2+ sources saturate) +
    0.5*depth (mean per-source score, capped to [0,1])."""
    if refused_reason:
        return 0.0
    if grounded is None and not scores:
        return None
    breadth = min(1.0, len(scores) / 2)
    capped = [max(0.0, min(1.0, float(s))) for s in scores]
    depth = (sum(capped) / len(capped)) if capped else 0.0
    value = 0.5 * breadth + 0.5 * depth
    return round(max(0.0, min(1.0, value)), 4)
