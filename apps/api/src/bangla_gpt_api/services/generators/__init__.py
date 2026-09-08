"""S2.3/S2.4/S2.6 content generators (chapter material, papers, lesson plans)."""

from bangla_gpt_api.services.generators.chapter_content import (
    CONTENT_JSON_MARKER,
    CONTENT_KEYS,
    CONTENT_SYSTEM_PROMPT,
    build_content_prompt,
    generate_chapter_content,
    parse_content_payload,
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

__all__ = [
    "CONTENT_JSON_MARKER",
    "CONTENT_KEYS",
    "CONTENT_SYSTEM_PROMPT",
    "LESSON_JSON_MARKER",
    "LESSON_KEYS",
    "LESSON_SYSTEM_PROMPT",
    "QP_JSON_MARKER",
    "QP_SYSTEM_PROMPT",
    "build_content_prompt",
    "build_lesson_prompt",
    "build_qp_prompt",
    "generate_chapter_content",
    "generate_lesson_plan",
    "generate_question_paper",
    "parse_content_payload",
    "parse_lesson_payload",
    "parse_qp_payload",
    "plan_counts",
    "validate_paper",
]
