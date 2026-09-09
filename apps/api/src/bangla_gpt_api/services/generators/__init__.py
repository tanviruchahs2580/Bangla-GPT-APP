"""S2.3/S2.4/S2.6 content generators (chapter material, papers, lesson plans)
plus the wave-1 generic teacher generators (worksheet, answer key, homework,
rubric)."""

from bangla_gpt_api.services.generators.answer_key import (
    ANSWER_KEY_JSON_MARKER,
    ANSWER_KEY_SYSTEM_PROMPT,
    build_answer_key_prompt,
    generate_answer_key,
    parse_answer_key_payload,
)
from bangla_gpt_api.services.generators.chapter_content import (
    CONTENT_JSON_MARKER,
    CONTENT_KEYS,
    CONTENT_SYSTEM_PROMPT,
    build_content_prompt,
    generate_chapter_content,
    parse_content_payload,
)
from bangla_gpt_api.services.generators.homework import (
    HOMEWORK_JSON_MARKER,
    HOMEWORK_SYSTEM_PROMPT,
    build_homework_prompt,
    generate_homework,
    parse_homework_payload,
)
from bangla_gpt_api.services.generators.lesson_plan import (
    LESSON_JSON_MARKER,
    LESSON_KEYS,
    LESSON_SYSTEM_PROMPT,
    build_lesson_prompt,
    generate_lesson_plan,
    parse_lesson_payload,
)
from bangla_gpt_api.services.generators.question_paper import (
    QP_JSON_MARKER,
    QP_SYSTEM_PROMPT,
    build_qp_prompt,
    generate_question_paper,
    parse_qp_payload,
    plan_counts,
    validate_paper,
)
from bangla_gpt_api.services.generators.rubric import (
    RUBRIC_JSON_MARKER,
    RUBRIC_SYSTEM_PROMPT,
    build_rubric_prompt,
    generate_rubric,
    parse_rubric_payload,
)
from bangla_gpt_api.services.generators.worksheet import (
    WORKSHEET_JSON_MARKER,
    WORKSHEET_SYSTEM_PROMPT,
    WORKSHEET_TIERS,
    build_worksheet_prompt,
    generate_worksheet,
    parse_worksheet_payload,
)

__all__ = [
    "ANSWER_KEY_JSON_MARKER",
    "ANSWER_KEY_SYSTEM_PROMPT",
    "CONTENT_JSON_MARKER",
    "CONTENT_KEYS",
    "CONTENT_SYSTEM_PROMPT",
    "HOMEWORK_JSON_MARKER",
    "HOMEWORK_SYSTEM_PROMPT",
    "LESSON_JSON_MARKER",
    "LESSON_KEYS",
    "LESSON_SYSTEM_PROMPT",
    "QP_JSON_MARKER",
    "QP_SYSTEM_PROMPT",
    "RUBRIC_JSON_MARKER",
    "RUBRIC_SYSTEM_PROMPT",
    "WORKSHEET_JSON_MARKER",
    "WORKSHEET_SYSTEM_PROMPT",
    "WORKSHEET_TIERS",
    "build_answer_key_prompt",
    "build_content_prompt",
    "build_homework_prompt",
    "build_lesson_prompt",
    "build_qp_prompt",
    "build_rubric_prompt",
    "build_worksheet_prompt",
    "generate_answer_key",
    "generate_chapter_content",
    "generate_homework",
    "generate_lesson_plan",
    "generate_question_paper",
    "generate_rubric",
    "generate_worksheet",
    "parse_answer_key_payload",
    "parse_content_payload",
    "parse_homework_payload",
    "parse_lesson_payload",
    "parse_qp_payload",
    "parse_rubric_payload",
    "parse_worksheet_payload",
    "plan_counts",
    "validate_paper",
]
