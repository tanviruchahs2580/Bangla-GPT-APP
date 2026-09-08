"""S4.2 AI Model Router -- rules-first, zero extra AI calls.

Routing contract (master spec 4.2):
- TOOL   -- teacher generation calls (content / lesson plan / question
            paper): always the MAIN model, and the call path already
            carries RAG evidence.
- COMPLEX-- long, multi-part, analytical student questions: MAIN model.
- SIMPLE -- short, single-fact questions: FAST model (when configured).

Rules are deterministic and cheap (pure string checks -- never an LLM
call), so classification adds no latency. The chosen route is propagated
via a ContextVar so the provider log line carries route+latency+cost
(chars as the cost proxy) for every request, same pattern as
request_id_var and the S4.1 education context.

Real fast-model selection on staging is a human decision (R8): with
GEMINI_FAST_MODEL unset the router still decides+logs routes, but both
routes serve the main provider.
"""

import re
from collections.abc import Iterable
from contextvars import ContextVar
from enum import StrEnum

# Goals that map to a teacher tool call (main model + RAG, per spec).
TOOL_GOALS = frozenset(
    {
        "chapter_content",
        "lesson_plan",
        "question_paper",
        "question_paper_replace",
    }
)


class Route(StrEnum):
    SIMPLE = "simple"
    COMPLEX = "complex"
    TOOL = "tool"


# Analytical markers (Bengali + English). Bengali written as codepoints to
# survive ASCII-only tooling: তুলনা / ব্যাখ্যা / বিশ্লেষণ / প্রমাণ.
_COMPLEX_MARKERS: tuple[str, ...] = (
    "\u09a4\u09c1\u09b2\u09a8\u09be",  # tulna  (compare)
    "\u09ac\u09cd\u09af\u09be\u0996\u09cd\u09af\u09be",  # byakhya (explain/analysis)
    "\u09ac\u09bf\u09b6\u09cd\u09b2\u09c7\u09b7\u09a3",  # bishleshon (analyse)
    "\u09aa\u09cd\u09b0\u09ae\u09be\u09a3",  # proman (prove)
    "compare",
    "explain why",
    "analyze",
    "derive",
    "prove that",
    "summarise the chapter",
    "summarize the chapter",
)

# 'ken evong kibaroe' -- why-and-how constructions need the main model.
_MULTI_HOP = "\u0995\u09c7\u09a8 \u098f\u09ac\u0982 \u0995\u09c0\u09ad\u09be\u09ac\u09c7"

_SENT_SPLIT = re.compile(r"[?.!\u0964]+")  # '?' '!' '.' + Bengali danda

_MAX_SIMPLE_CHARS = 160
_MAX_SIMPLE_QUESTIONS = 2
_MAX_SIMPLE_SENTENCES = 2


def classify(text: str, goal: str | None = None) -> Route:
    """Deterministic rules-first routing decision (never an LLM call)."""
    if goal in TOOL_GOALS:
        return Route.TOOL
    t = (text or "").strip()
    if len(t) > _MAX_SIMPLE_CHARS:
        return Route.COMPLEX
    questions = t.count("?") + t.count("\u0965")  # '?' + Bengali question mark
    if questions > _MAX_SIMPLE_QUESTIONS:
        return Route.COMPLEX
    lowered = t.lower()
    if any(marker in lowered for marker in _COMPLEX_MARKERS) or _MULTI_HOP in t:
        return Route.COMPLEX
    sentences = [s for s in _SENT_SPLIT.split(t) if s.strip()]
    if len(sentences) > _MAX_SIMPLE_SENTENCES:
        return Route.COMPLEX
    return Route.SIMPLE


def fast_eligible(route: Route, fast_provider: object | None) -> bool:
    """Only SIMPLE requests may move to the fast provider, and only when one
    is actually configured (GEMINI_FAST_MODEL unset -> main serves all)."""
    return route is Route.SIMPLE and fast_provider is not None


def route_distribution(items: Iterable[tuple[str, str | None]]) -> dict[str, int]:
    """Classify replayed sample traffic: [(text, goal), ...] -> counts."""
    counts = {route.value: 0 for route in Route}
    for text, goal in items:
        counts[classify(text, goal).value] += 1
    return counts


def simple_share(counts: dict[str, int]) -> float:
    total = sum(counts.values())
    return counts.get(Route.SIMPLE.value, 0) / total if total else 0.0


# --- request-scoped propagation (mirrors request_id_var / S4.1 context) -----

_current_route: ContextVar[str | None] = ContextVar("ai_route", default=None)


def set_current_route(route: Route | str | None) -> None:
    _current_route.set(route.value if isinstance(route, Route) else route)


def get_current_route() -> str | None:
    return _current_route.get()
