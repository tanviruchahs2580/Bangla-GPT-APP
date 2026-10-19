"""Section labels for structured AI answers (SYSTEM_PROMPT rule ৬ / step 1.4).

Kept in a dependency-free module so both the tutor service and the mock
provider can share one source of truth without an import cycle. The labels are
part of the prompt contract, so they live in the registry like every other
prompt: ``prompts/tutor_system.md`` must contain each label verbatim (pinned
in tests/test_rag2_prompt_registry.py and test_safety_v2.py).
"""

from bangla_gpt_api.services.prompt_registry import load_prompt

SECTION_SIMPLE = "সহজ ব্যাখ্যা:"
SECTION_EXAMPLE = "উদাহরণ:"
SECTION_POINTS = "মূল বিষয়:"
SECTION_CHECK = "তুমি বুঝেছ?"


# low-data mode asks the model for a 1-2 sentence answer.
# the text is a registered prompt file (prompts/tutor_short_answer.md), not an
# inline string; the registry is the only copy.
SHORT_ANSWER_INSTRUCTION = load_prompt("tutor_short_answer").text
