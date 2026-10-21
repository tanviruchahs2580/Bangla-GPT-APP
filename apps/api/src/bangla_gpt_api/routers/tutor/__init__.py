"""Tutor routes, split by surface (C-03): the single-shot ask, the
conversation history, the streamed chat, feedback, and product events.

Split of the 26-name module ``routers/tutor.py`` along its seams (C-03).
The sub-routers are included in the original declaration order, so the
served route table -- which `docs/route_baseline.md` records and the
OpenAPI document pins -- is unchanged: verified with
`.audit/tmp/r5/routes_dump.py` and `scripts/gen_api_docs.py --check`.
"""

from fastapi import APIRouter

from . import _ask, _chat, _conversations, _events, _feedback
from ._chat import _chat_history as _chat_history  # noqa: F401
from ._shared import DEFAULT_INFLIGHT_CHAT as DEFAULT_INFLIGHT_CHAT  # noqa: F401
from ._shared import DEFAULT_INFLIGHT_SINGLE as DEFAULT_INFLIGHT_SINGLE  # noqa: F401
from ._shared import INFLIGHT_ENV_KEY as INFLIGHT_ENV_KEY  # noqa: F401
from ._shared import SSE_STREAM_HEADERS as SSE_STREAM_HEADERS  # noqa: F401
from ._shared import _concurrency_limiter as _concurrency_limiter  # noqa: F401
from ._shared import _inflight_limit as _inflight_limit  # noqa: F401
from ._shared import effective_inflight_limit as effective_inflight_limit  # noqa: F401

#: Inclusion order mirrors the pre-split file (route precedence).
router = APIRouter()
for _sub in (_ask, _conversations, _chat, _feedback, _events):
    router.include_router(_sub.router)

__all__ = [
    "DEFAULT_INFLIGHT_CHAT",
    "DEFAULT_INFLIGHT_SINGLE",
    "INFLIGHT_ENV_KEY",
    "SSE_STREAM_HEADERS",
    "_chat_history",
    "_concurrency_limiter",
    "_inflight_limit",
    "effective_inflight_limit",
    "router",
]
