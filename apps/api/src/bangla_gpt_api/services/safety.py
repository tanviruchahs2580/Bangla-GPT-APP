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


def screen_question(question: str) -> SafetyVerdict:
    """Return a verdict for a free-text question."""
    for name, pattern in _COMPILED:
        if pattern.search(question):
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
