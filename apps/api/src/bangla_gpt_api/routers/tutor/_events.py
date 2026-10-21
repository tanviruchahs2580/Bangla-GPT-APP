"""Tutor routes, split by surface (C-03): the single-shot ask, the
conversation history, the streamed chat, feedback, and product events.

_events — C-03 split of ``routers/tutor.py``: same paths, same order, same
guards as the single module it came from.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request

from bangla_gpt_api.db.models import (
    AnalyticsEventRow,
)
from bangla_gpt_api.logging_config import json_log
from bangla_gpt_api.routers._error_contract import AUTH_GUARD_RESPONSES
from bangla_gpt_api.schemas import (
    AnalyticsEvent,
)

from ..common import (
    _sanitize_event_props,
)
from ..deps import (
    CurrentUser,
    DbSession,
)

router = APIRouter(responses=AUTH_GUARD_RESPONSES)

logger = logging.getLogger(__name__)


@router.post("/events", status_code=202)
def record_event(
    payload: AnalyticsEvent, request: Request, db: DbSession, user: CurrentUser
) -> dict:
    # Privacy: log only which prop keys were sent, never their values —
    # props are arbitrary client input and may contain personal data.
    json_log(
        logger,
        logging.INFO,
        "product_event",
        name=payload.name,
        props_keys=sorted(payload.props.keys()),
        role=user.role,
    )
    # persist the event server-side after sanitization (drop
    # PII-flavoured keys, primitive values, 40-char strings). The trail
    # table has no FK by design: product analytics survive account
    # deletion as an aggregate-only record (user_id included).
    db.add(
        AnalyticsEventRow(
            user_id=user.id,
            name=payload.name,
            role=user.role,
            props=_sanitize_event_props(dict(payload.props)),
        )
    )
    db.commit()
    return {"status": "accepted"}
