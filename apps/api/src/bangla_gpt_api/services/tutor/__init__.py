"""AI tutor service — the 1814-line ``services/tutor.py`` split by seam (C-03).

The public surface is unchanged: `TutorService`, `StreamEvent` and every
module-level name the single module exposed are importable from here, which is
what `routers/`, `evaluation/` and the generators rely on.

The seams, and why they are seams:

``prompts``     the text the model reads (system prompt + its version, the
                instructions, the evidence delimiters) — a prompt edit and its
                version bump stay one diff in one file;
``evidence``    query normalization, evidence rendering, prompt building — the
                material between retrieval and the provider call;
``signals``     cheap side-effect-free predicates and knobs (heartbeats,
                hint-first, homework detection, safety screen);
``state``       the attributes the class owns, declared once so the mixins
                type-check (and so mypy verifies ``__init__`` against them),
                plus the method surface for the type checker;
``retrieval``   retrieval, the grounding gate and citation selection;
``generation``  provider selection, streaming plumbing, the generation calls;
``assembly``    post-check, response assembly, the one-shot grounding retry;
``ask``         the single-shot entry point;
``service``     `TutorService` (constructor + `ask_stream`) and `StreamEvent`.

Method bodies moved verbatim: `self` dispatch is unchanged, so a subclass that
overrides a helper still wins and behaviour is what it was.
"""

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
from bangla_gpt_api.services.tutor.events import (
    StreamEvent,
)
from bangla_gpt_api.services.tutor.evidence import (
    CITATION_SELECTION_FLOOR,
    build_evidence_prompt,
    build_evidence_prompt_with_selection,
    normalize_query,
    render_evidence,
)
from bangla_gpt_api.services.tutor.prompts import (
    EVIDENCE_CLOSE,
    EVIDENCE_ONLY_HEADER,
    EVIDENCE_OPEN,
    GOAL_STUDY,
    GROUNDING_RETRY_INSTRUCTION,
    HINT_FIRST_INSTRUCTION,
    IMAGE_UNREADABLE_ANSWER,
    INSUFFICIENT_EVIDENCE_ANSWER,
    PROMPT_VERSION,
    STUDY_STEPS_INSTRUCTION,
    SYSTEM_PROMPT,
    VISION_UNSUPPORTED_ANSWER,
)
from bangla_gpt_api.services.tutor.service import (
    TutorService,
)
from bangla_gpt_api.services.tutor.signals import (
    HINT_FIRST_ENV,
    STREAM_EVENT_TYPES,
    STREAM_HEARTBEAT_ENV,
    STREAM_HEARTBEAT_SECONDS,
    hint_first_enabled,
    is_homework_like,
    sanitize_image_payload,
    stream_heartbeat_seconds,
)

__all__ = [
    "CITATION_SELECTION_FLOOR",
    "EVIDENCE_CLOSE",
    "EVIDENCE_ONLY_HEADER",
    "EVIDENCE_OPEN",
    "GOAL_STUDY",
    "GROUNDING_RETRY_INSTRUCTION",
    "HINT_FIRST_ENV",
    "HINT_FIRST_INSTRUCTION",
    "IMAGE_UNREADABLE_ANSWER",
    "INSUFFICIENT_EVIDENCE_ANSWER",
    "PROMPTS_DIR_ENV",
    "PROMPT_VERSION",
    "SECTION_CHECK",
    "SECTION_EXAMPLE",
    "SECTION_POINTS",
    "SECTION_SIMPLE",
    "SHORT_ANSWER_INSTRUCTION",
    "STREAM_EVENT_TYPES",
    "STREAM_HEARTBEAT_ENV",
    "STREAM_HEARTBEAT_SECONDS",
    "STUDY_STEPS_INSTRUCTION",
    "SYSTEM_PROMPT",
    "VISION_UNSUPPORTED_ANSWER",
    "PromptSpec",
    "StreamEvent",
    "TutorService",
    "build_evidence_prompt",
    "build_evidence_prompt_with_selection",
    "hint_first_enabled",
    "is_homework_like",
    "load_prompt",
    "normalize_query",
    "prompts_dir",
    "render_evidence",
    "render_image_text_block",
    "sanitize_evidence",
    "sanitize_image_payload",
    "sanitize_image_text",
    "stream_heartbeat_seconds",
]
