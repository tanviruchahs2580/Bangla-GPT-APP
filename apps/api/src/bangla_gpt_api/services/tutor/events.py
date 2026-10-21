"""`StreamEvent`, the type `ask_stream` yields (C-03 split of services/tutor.py).

Its own module because both the streaming seam and the type-checking
surface of `TutorState` name it, and importing it into `state.py` from
`service.py` would close a module-level layer cycle.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from bangla_gpt_api.schemas import AskResponse


@dataclass
class StreamEvent:
    """One item of a streaming tutoring turn."""

    type: str  # token | citation | heartbeat | error | final
    #: citation: {"sources": [...], "citation_verified": true}
    #: heartbeat: {"interval_seconds": n}; error: {"code", "recoverable"};
    #: final carries ``response``. See the streaming contract block above.
    text: str | None = None
    response: AskResponse | None = None
    extra: dict = field(default_factory=dict)
