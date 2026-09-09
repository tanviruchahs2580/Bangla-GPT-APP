"""S4.1 Education Context Engine.

ONE central place builds the education context attached to every AI call:
who is asking (role/class), what topic (subject/chapter), why (goal), how
much conversation precedes it (history_summary) and what we already know
about mastery (mastery_snapshot).

Rules honoured here:
- The context is TRUSTED APP TEXT injected into the USER prompt; system
  prompts stay byte-identical so their secrecy/injection protections (R5)
  never move or change.
- log_fields() is safe for observability: counts, ids, concepts -- never
  message content or PII (R11, same discipline as product_event props).
"""

from collections.abc import Mapping
from contextvars import ContextVar
from dataclasses import dataclass, field

# --- the central structure ------------------------------------------------


@dataclass(frozen=True)
class RequestContext:
    """Everything the AI layer is allowed to know about one request (S4.1)."""

    role: str
    class_level: int
    subject: str | None = None
    chapter_id: str | None = None
    goal: str = "question"  # question | chat | reteach | quiz_explain | ...
    history_summary: str = "0 turns"  # counts/strategy only, never content
    mastery_snapshot: Mapping[str, float] = field(default_factory=dict)
    # Wave 2: gated personalization line (weak-chapter facts + explanation
    # style directive). Empty string -> NO personalization is rendered; the
    # caller leaves it empty when the student disabled their learning memory.
    memory_block: str = ""

    def log_fields(self) -> dict[str, object]:
        """JSON-safe observability fields (eval + cost attribution)."""
        return {
            "ai_role": self.role,
            "ai_class_level": self.class_level,
            "ai_subject": self.subject or "",
            "ai_chapter": self.chapter_id or "",
            "ai_goal": self.goal,
            "ai_history": self.history_summary,
            "ai_mastery_concepts": len(self.mastery_snapshot),
        }

    def render_block(self) -> str:
        """Trusted app-text header prepended to the USER prompt.

        ASCII keys keep it stable for tests and provider-agnostic; the model
        sees structured education context, never raw user history.
        """
        mastery = (
            ",".join(f"{c}={p:.0f}" for c, p in sorted(self.mastery_snapshot.items()))
            if self.mastery_snapshot
            else "none"
        )
        # Wave 2: the personalization line renders ONLY when the caller put
        # content in memory_block (memory enabled). Byte-identical output
        # when empty -- existing consumers/tests are unaffected.
        memory_line = f"\nmemory: {self.memory_block}" if self.memory_block else ""
        return (
            "[education-context]\n"
            f"role={self.role} class_level={self.class_level} subject={self.subject or 'any'}"
            f" chapter={self.chapter_id or 'any'} goal={self.goal}"
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
