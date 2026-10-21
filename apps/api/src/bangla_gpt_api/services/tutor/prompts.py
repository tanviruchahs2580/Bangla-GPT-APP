"""The text the model reads: the answer instructions, the evidence-block
delimiters and the system prompt (with its version). Kept in one module so
a prompt edit and its version bump are one diff in one file.

prompts — C-03 split of ``services/tutor.py``: moved verbatim.
"""

from __future__ import annotations

from bangla_gpt_api.services.answer_structure import (  # noqa: F401 (re-export for prompt/mock/tests)
    SECTION_CHECK,
    SECTION_EXAMPLE,
    SECTION_POINTS,
    SECTION_SIMPLE,
    SHORT_ANSWER_INSTRUCTION,
)
from bangla_gpt_api.services.prompt_registry import (  # noqa: F401 (re-export)
    PROMPTS_DIR_ENV,
    PromptSpec,
    load_prompt,
    prompts_dir,
)
from bangla_gpt_api.services.safety import (
    render_image_text_block as render_image_text_block,
)
from bangla_gpt_api.services.safety import (
    sanitize_evidence as sanitize_evidence,
)
from bangla_gpt_api.services.safety import (
    sanitize_image_text as sanitize_image_text,
)

INSUFFICIENT_EVIDENCE_ANSWER = (
    "উত্তরটি পাঠ্যবইয়ের বিষয়বস্তুর ভিত্তিতে দেওয়া সম্ভব নয়। অনুগ্রহ করে পাঠ্যবইয়ের সংশ্লিষ্ট অধ্যায় থেকে প্রশ্ন করুন।"
)


# AUD-A2-03 / A6-01: the one-shot regeneration instruction used when the first
# answer fails the post-generation grounding check (citation overlap or an
# arithmetic contradiction). Trusted app text, prepended ahead of the evidence,
# same placement rule as the re-teach instruction. NEEDS NATIVE REVIEW.
GROUNDING_RETRY_INSTRUCTION = load_prompt("tutor_grounding_retry").text


# AUD-A2-19 / A11-03: hint-first instruction for homework-like prompts and the
# step-by-step instruction injected for study-mode turns (context goal).
HINT_FIRST_INSTRUCTION = load_prompt("tutor_hint_first").text


STUDY_STEPS_INSTRUCTION = load_prompt("tutor_study_steps").text


# (vision contract): honest refusal for LLM_PROVIDER=mock, which cannot
# see images. A NEW constant -- the four protected SYSTEM_PROMPT constants and
# INSUFFICIENT_EVIDENCE_ANSWER above stay exactly as they are. The copy never
# claims to have looked at the picture (refused_reason='vision_unsupported').
VISION_UNSUPPORTED_ANSWER = (
    "দুঃখিত, এই সংস্করণে ছবি থেকে উত্তর দেওয়া এখনো সম্ভব হয়নি। "
    "অনুগ্রহ করে প্রশ্নটি লিখে পাঠান — আমি পাঠ্যবইয়ের ভিত্তিতে উত্তর দেব।"
)


# AUD-A2-17 / A6-09: honest refusal for an image that cannot be read (blank,
# blurry, too small, or not decodable). Better a clear "send a clearer photo"
# than a vision model guessing at a picture nobody can read.
IMAGE_UNREADABLE_ANSWER = (
    "দুঃখিত, ছবিটি পড়া যায়নি (অস্পষ্ট, খুব ছোট বা ক্ষতিগ্রস্ত)। "
    "অনুগ্রহ করে পরিষ্কার ছবি আবার পাঠান, অথবা প্রশ্নটি লিখে পাঠান।"
)


# A9-03 graceful degradation: when NO provider can serve the turn, the
# student still gets the retrieved textbook passages with an honest notice
# instead of a dead end. Never marked grounded (no model wrote it) and never
# carries model citations -- the passages are quoted verbatim with their ids.
EVIDENCE_ONLY_HEADER = (
    "দুঃখিত, AI উত্তর এই মুহূর্তে দেওয়া যাচ্ছে না। তবে প্রশ্নের সঙ্গে সম্পর্কিত পাঠ্যবইয়ের অংশগুলো নিচে দেওয়া হলো:"
)


EVIDENCE_OPEN = "<evidence>"


EVIDENCE_CLOSE = "</evidence>"


#: Context goal the router sets for a study-mode turn; study mode appends the
#: step-by-step instruction (prompts/tutor_study_steps.md).
GOAL_STUDY = "study"


# Canonical non-answer phrasing the SYSTEM_PROMPT (rule ৪) instructs the
# model to use when the evidence does not contain the answer. Detecting it
# keeps the ``grounded`` flag honest: a "not in the textbook" reply is a
# refusal, not a grounded answer with citations attached.
_MODEL_REFUSAL_MARKER = "পাঠ্যবইয়ে নেই"


# Sentinel yielded by _stream_with_fallback when no provider can serve the
# stream. A real delta is always a non-empty str, so identity comparison is
# safe and the value can never collide with provider output.
_OUTAGE = object()


# Streamed when no provider could serve the turn. This is an outage notice,
# not textbook content — the stream path must never mark it grounded.
_UNAVAILABLE_ANSWER = "দুঃখিত, AI সেবা এই মুহূর্তে ব্যবহার করা যাচ্ছে না। অনুগ্রহ করে পরে আবার চেষ্টা করুন।"


_ZERO_WIDTH_TABLE = str.maketrans("", "", "\u200b\u200c\u200d\ufeff")


# Prompt-injection guard: corpus chunks are untrusted data. They are
# wrapped in <evidence> delimiters and the system rule explicitly states
# that anything inside the delimiters is quoted data, never instructions.
# The student's own question is likewise wrapped and declared untrusted.
# The text lives in prompts/tutor_system.md (owner + changelog there).
_SYSTEM_PROMPT_SPEC = load_prompt("tutor_system")


SYSTEM_PROMPT = _SYSTEM_PROMPT_SPEC.text


#: Machine-derived prompt version (A5-02 / I-03): registry id + SemVer version
#: + the digest of the exact text in this build, recorded in every generation
#: trace. Deriving the digest instead of hand-maintaining a version string
#: means a prompt edit can never leave a stale version behind in a trace
#: record; the SemVer part comes from the registry changelog.
PROMPT_VERSION = _SYSTEM_PROMPT_SPEC.trace_version
