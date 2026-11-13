"""Education Context Engine.

ONE central place builds the education context attached to every AI call:
who is asking (role/class), what topic (subject/chapter), why (goal), how
much conversation precedes it (history_summary) and what we already know
about mastery (mastery_snapshot).

Rules honoured here:
- The context is TRUSTED APP TEXT injected into the USER prompt; system
  prompts stay byte-identical so their secrecy/injection protections
  never move or change. Client-owned *values* (subject, chapter, the
  personalization line) are still untrusted: they are length-capped and
  delimiter-escaped before interpolation (RAG-001), so a value can neither
  forge an ``<evidence>`` block nor close ``[education-context]`` early.
- log_fields is safe for observability: counts, ids, concepts -- never
  message content or PII (, same discipline as product_event props).
"""

import re
from collections.abc import Mapping
from contextvars import ContextVar
from dataclasses import dataclass, field

from bangla_gpt_api.services.pii import redact_pii

# --- prompt-delimiter escaping --------------------------------------------
# ONE implementation for every untrusted prompt input. It lives here because
# services.tutor imports this module (the reverse import would be a cycle);
# services.tutor.sanitize_evidence delegates to it, so the education-context
# fields and the evidence/history/question blocks escape delimiter collisions
# by exactly the same rule. The delimiter pairs below are the trust hierarchy
# the prompt is built from: the evidence pair, the vision pair, the
# user-question pair and this module's education-context pair.
_EVIDENCE_CLOSE_RE = re.compile(r"</\s*evidence\s*>", re.IGNORECASE)
_EVIDENCE_OPEN_RE = re.compile(r"<\s*evidence\s*>", re.IGNORECASE)
_IMAGE_TAG_RE = re.compile(r"<\s*/?\s*attached_image\s*>", re.IGNORECASE)
_USER_QUESTION_RE = re.compile(r"<\s*/?\s*user_question\s*>", re.IGNORECASE)
_CONTEXT_CLOSE_RE = re.compile(r"\[\s*/\s*education-context\s*\]", re.IGNORECASE)
_CONTEXT_OPEN_RE = re.compile(r"\[\s*education-context\s*\]", re.IGNORECASE)


def sanitize_prompt_text(text: str) -> str:
    """Neutralize prompt-delimiter collisions inside untrusted text.

    A collision is rewritten in place, never removed: the model still sees
    what was written, but the prompt's delimiter structure cannot be forged.
    """
    text = _EVIDENCE_CLOSE_RE.sub("<&#47;evidence>", text)
    text = _EVIDENCE_OPEN_RE.sub("<&#91;evidence>", text)
    text = _IMAGE_TAG_RE.sub("<&#91;attached_image&#93;>", text)
    text = _USER_QUESTION_RE.sub("<&#91;user_question&#93;", text)
    text = _CONTEXT_CLOSE_RE.sub("[&#47;education-context]", text)
    return _CONTEXT_OPEN_RE.sub("[&#91;education-context]", text)


#: Bounds re-applied where client-owned context fields enter the prompt
#: (RAG-001): the same lengths the request schemas and the DB columns allow
#: (subject VARCHAR(60), chapter VARCHAR(200)). Re-applying them here keeps a
#: direct render_block caller from blowing the prompt budget with one field.
MAX_CONTEXT_SUBJECT_CHARS = 60
MAX_CONTEXT_CHAPTER_CHARS = 200

# --- the central structure ------------------------------------------------


@dataclass(frozen=True)
class RequestContext:
    """Everything the AI layer is allowed to know about one request."""

    role: str
    class_level: int
    subject: str | None = None
    chapter_id: str | None = None
    goal: str = "question"  # question | chat | reteach | quiz_explain |...
    history_summary: str = "0 turns"  # counts/strategy only, never content
    mastery_snapshot: Mapping[str, float] = field(default_factory=dict)
    # gated personalization line (weak-chapter facts + explanation
    # style directive). Empty string -> NO personalization is rendered; the
    # caller leaves it empty when the student disabled their learning memory.
    memory_block: str = ""

    def log_fields(self) -> dict[str, object]:
        """JSON-safe observability fields (eval + cost attribution).

        ``ai_subject``/``ai_chapter`` are client-owned values that land in
        metering rows, so they get the same treatment ``render_block`` gives
        the prompt: length-capped here, and PII-redacted (services.pii — a
        phone typed into the subject field must not survive into ai_usage).
        """
        subject = self.subject or ""
        chapter = self.chapter_id or ""
        if subject:
            subject = redact_pii(subject[:MAX_CONTEXT_SUBJECT_CHARS])[0]
        if chapter:
            chapter = redact_pii(chapter[:MAX_CONTEXT_CHAPTER_CHARS])[0]
        return {
            "ai_role": self.role,
            "ai_class_level": self.class_level,
            "ai_subject": subject,
            "ai_chapter": chapter,
            "ai_goal": self.goal,
            "ai_history": self.history_summary,
            "ai_mastery_concepts": len(self.mastery_snapshot),
        }

    def render_block(self) -> str:
        """Trusted app-text header prepended to the USER prompt.

        ASCII keys keep it stable for tests and provider-agnostic; the model
        sees structured education context, never raw user history. The
        interpolated values are client-owned, so each one is length-capped
        and delimiter-escaped (RAG-001) before interpolation; the app-authored
        wrapper and keys stay raw, so a legitimate request renders
        byte-identically.
        """
        mastery = (
            ",".join(f"{c}={p:.0f}" for c, p in sorted(self.mastery_snapshot.items()))
            if self.mastery_snapshot
            else "none"
        )
        # the personalization line renders ONLY when the caller put
        # content in memory_block (memory enabled). Byte-identical output
        # when empty -- existing consumers/tests are unaffected.
        memory_line = (
            f"\nmemory: {sanitize_prompt_text(self.memory_block)}" if self.memory_block else ""
        )
        subject = sanitize_prompt_text((self.subject or "any")[:MAX_CONTEXT_SUBJECT_CHARS])
        chapter = sanitize_prompt_text((self.chapter_id or "any")[:MAX_CONTEXT_CHAPTER_CHARS])
        return (
            "[education-context]\n"
            f"role={self.role} class_level={self.class_level} subject={subject}"
            f" chapter={chapter} goal={self.goal}"
            f" history={self.history_summary} mastery_recent={mastery}"
            f"{memory_line}"
            "\n[/education-context]"
        )


# --- pure helpers (unit-tested) -------------------------------------------


def history_summary(turns: int, strategy: str | None = None) -> str:
    """Compact history label: counts + last strategy, never message text."""
    base = f"{turns} turns"
    return f"{base}, strategy={strategy}" if strategy else base


def snapshot_mastery(
    accuracy_by_concept: Mapping[str, float | None], limit: int = 8
) -> dict[str, float]:
    """Weakest-first mastery snapshot capped at `limit` concepts.

    Input: per-concept accuracy percentages (None = ungraded -> skipped).
    """
    scored = [(c, float(a)) for c, a in accuracy_by_concept.items() if a is not None]
    scored.sort(key=lambda item: (item[1], item[0]))
    return {c: round(p, 1) for c, p in scored[:limit]}


# --- request-scoped propagation (mirrors request_id_var logging pattern) --

_current: ContextVar[RequestContext | None] = ContextVar("education_context", default=None)


def set_current_context(ctx: RequestContext | None) -> None:
    _current.set(ctx)


def get_current_context() -> RequestContext | None:
    return _current.get()
