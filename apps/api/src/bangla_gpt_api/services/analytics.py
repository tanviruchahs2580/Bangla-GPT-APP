"""Server-side product analytics: sanitized event props and the queued writer.

Split from ``routers/common.py`` (F-077): the analytics trail is a service
concern -- one sanitizer (F-039) and one queued row writer used by routers.
``routers/common.py`` re-exports these names for the import sites that predate
the split.
"""

import re
from typing import Any

from sqlalchemy.orm import Session

from bangla_gpt_api.db.models import AnalyticsEventRow
from bangla_gpt_api.services.pii import redact_pii, redacted_total

# POST /events props are persisted; anything that could smuggle PII (keys
# whose NAME hints at free text or identifiers) is dropped before it can ever
# reach the database, values are primitive-only and strings are truncated.
_EVENT_DROP_KEY_RE = re.compile(
    r"email|name|phone|address|token|code|password|question|message|content|answer",
    re.IGNORECASE,
)

_EVENT_PROP_MAX_LEN = 40

# F-039: the key drop-list alone left VALUES wide open -- a probe stored
# {"note": "call me at 01898765432"} and {"label": "Karim Rahman"} verbatim,
# so any authenticated client could persist child text for the 180-day
# analytics window. The value side has an allowlist now: bool/int/float pass
# as before, and a string passes only when it is a short machine code --
# lowercase ASCII letters/digits plus "_.:-", no spaces, no non-ASCII (so
# Bangla free text is dropped), no six-or-more-digit run (BD mobile numbers
# and NID runs) and no redact_pii match. Free text is dropped, not stored.
_EVENT_SAFE_STRING_RE = re.compile(r"^[a-z0-9][a-z0-9_.:\-]{0,39}$")
_EVENT_DIGIT_RUN_RE = re.compile(r"\d{6,}")


def _event_string_value_allowed(value: str) -> bool:
    """True when a prop string is a safe machine code (F-039)."""
    if not value or len(value) > _EVENT_PROP_MAX_LEN:
        return False
    if _EVENT_DIGIT_RUN_RE.search(value) or _EVENT_SAFE_STRING_RE.match(value) is None:
        return False
    _, counts = redact_pii(value)
    return redacted_total(counts) == 0


def _sanitize_event_props(props: dict[str, Any]) -> dict[str, Any]:
    """Primitives only, drop-listed keys removed, strings machine-code shaped."""
    clean: dict[str, Any] = {}
    for key, value in props.items():
        if _EVENT_DROP_KEY_RE.search(str(key)):
            continue
        if isinstance(value, (bool, int, float)):
            clean[str(key)[:_EVENT_PROP_MAX_LEN]] = value
        elif isinstance(value, str):
            truncated = value[:_EVENT_PROP_MAX_LEN]
            if _event_string_value_allowed(truncated):
                clean[str(key)[:_EVENT_PROP_MAX_LEN]] = truncated
        # anything else -- non-primitive, and free-text strings -- is dropped
    return clean


def _record_analytics(
    db: Session,
    actor_id: int | None,
    actor_role: str | None,
    name: str,
    props: dict[str, Any] | None = None,
) -> None:
    """Queue one sanitized AnalyticsEventRow (same drop-list as POST /events).

    Adds only -- the caller's commit persists it. Props must be code/count
    flavoured; anything PII-shaped is stripped by ``_sanitize_event_props``.
    """
    db.add(
        AnalyticsEventRow(
            user_id=actor_id,
            name=name[:64],
            role=actor_role[:40] if actor_role else None,
            props=_sanitize_event_props(dict(props or {})),
        )
    )
