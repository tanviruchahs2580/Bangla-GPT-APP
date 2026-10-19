"""H-03: the HTTP-semantics helpers — ``Idempotency-Key`` and ``If-Match``.

Two gaps the audit found were real: no POST anywhere accepted an
``Idempotency-Key``, so a client that retried after a timeout could repeat a
side effect (and could never recover a response it lost), and no update route
spoke ``ETag``/``If-Match``, so two concurrent editors silently lost one
edit. Both are opt-in and additive -- a request that sends neither header
behaves exactly as before.

Idempotency-Key
---------------
``run_once`` claims the key in the shared cache with the atomic
``set_json_nx_strict`` primitive (the same one refresh-token rotation uses),
then:

* a duplicate that arrives while the first call is still running gets
  ``409 idempotency_in_progress`` rather than repeating the side effect;
* a duplicate after the first call completed gets the stored status and body
  back, with ``Idempotent-Replay: true``;
* the key is scoped by route + user id and the raw client value is hashed, so
  one caller can neither read another's response nor inject a cache key;
* deterministic client failures (4xx, except 429) are replayed too; a 5xx or
  a rate-limit refusal leaves a short-lived claim so an immediate retry cannot
  duplicate a side effect that may have partially committed, and expires
  quickly so the operator can retry;
* if the cache backend is unreachable the request simply proceeds
  (fail-open): refusing every write because a dedupe cache is down would be a
  self-inflicted outage, and the request itself is still valid.

ETag / If-Match
---------------
``document_etag`` builds a strong validator from the resource's serialized
content; ``require_if_match`` enforces a presented ``If-Match`` and answers
``412 precondition_failed`` on a stale one. Sending no ``If-Match`` keeps the
legacy last-write-wins behaviour, so no existing client breaks.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, TypeVar

from fastapi import Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from bangla_gpt_api.caching import CacheUnavailable

logger = logging.getLogger(__name__)

IDEMPOTENCY_HEADER = "Idempotency-Key"
#: How long a completed response stays replayable. A day covers the realistic
#: "the client timed out, the operator retried" window.
IDEMPOTENCY_TTL_SECONDS = 24 * 3600.0
#: How long a failed/refused attempt keeps its claim. Long enough that an
#: immediate retry cannot duplicate a partially-committed side effect, short
#: enough that a real operator retry is not locked out.
IDEMPOTENCY_FAILED_TTL_SECONDS = 60.0
#: Client-supplied key bounds (an RFC 8941-ish token is expected in practice).
IDEMPOTENCY_MIN_KEY_LENGTH = 8
IDEMPOTENCY_MAX_KEY_LENGTH = 255

T = TypeVar("T")

#: The header, declared as a FastAPI parameter so it appears in the served
#: OpenAPI document (a client must be able to discover it).
IdempotencyKeyHeader = Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)]


def idempotency_key(request: Request) -> str | None:
    """The validated ``Idempotency-Key`` header, or ``None`` when absent."""
    return validate_idempotency_key(request.headers.get(IDEMPOTENCY_HEADER))


def validate_idempotency_key(raw: str | None) -> str | None:
    """Validate a declared ``Idempotency-Key`` parameter value."""
    if raw is None:
        return None
    key = raw.strip()
    if not IDEMPOTENCY_MIN_KEY_LENGTH <= len(key) <= IDEMPOTENCY_MAX_KEY_LENGTH:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "invalid_idempotency_key",
                "message": (
                    f"{IDEMPOTENCY_HEADER} must be "
                    f"{IDEMPOTENCY_MIN_KEY_LENGTH}-{IDEMPOTENCY_MAX_KEY_LENGTH} characters"
                ),
            },
        )
    return key


def scoped_idempotency_key(scope: str, user_id: int | str, key: str) -> str:
    """Cache key for one caller's key: namespaced, hashed, unguessable."""
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
    return f"idem:{scope}:{user_id}:{digest}"


def _store(cache: Any, cache_key: str, value: dict[str, Any], ttl: float) -> None:
    try:
        cache.set_json_strict(cache_key, value, ttl)
    except CacheUnavailable:  # pragma: no cover - memory backend never raises
        logger.warning("idempotency: could not store replay for %s", cache_key)


def _load(cache: Any, cache_key: str) -> dict[str, Any] | None:
    try:
        # Fail-soft on purpose: if the store is down we cannot prove a replay,
        # so the request proceeds rather than being refused.
        value = cache.get_json(cache_key)
    except CacheUnavailable:  # pragma: no cover - memory backend never raises
        return None
    return value if isinstance(value, dict) else None


def _replay(stored: dict[str, Any]) -> JSONResponse:
    return JSONResponse(
        stored["body"],
        status_code=int(stored["status"]),
        headers={"Idempotent-Replay": "true"},
    )


async def run_once(
    *,
    cache: Any,
    scope: str,
    user_id: int | str,
    key: str | None,
    produce: Callable[[], Awaitable[T]],
    success_status: int = 200,
) -> T | JSONResponse:
    """Run ``produce`` at most once per (``scope``, ``user_id``, ``key``).

    ``cache`` may be ``None`` (no cache configured): the call then just runs.
    """
    if not key or cache is None:
        return await produce()
    cache_key = scoped_idempotency_key(scope, user_id, key)
    try:
        claimed = cache.set_json_nx_strict(
            cache_key, {"state": "in_flight"}, IDEMPOTENCY_TTL_SECONDS
        )
    except CacheUnavailable:  # pragma: no cover - memory backend never raises
        return await produce()
    if not claimed:
        return _duplicate(cache, cache_key)
    try:
        result = await produce()
    except HTTPException as exc:
        _record_failure(cache, cache_key, exc)
        raise
    body: Any = result.model_dump(mode="json") if isinstance(result, BaseModel) else result
    _store(
        cache,
        cache_key,
        {"state": "done", "status": success_status, "body": body},
        IDEMPOTENCY_TTL_SECONDS,
    )
    return result


def _duplicate(cache: Any, cache_key: str) -> JSONResponse:
    """The answer for a second request carrying the same Idempotency-Key.

    A finished first request is replayed byte-for-byte; one still in flight is
    a 409 (retry shortly) rather than a second execution.
    """
    stored = _load(cache, cache_key)
    if stored is not None and stored.get("state") == "done":
        return _replay(stored)
    raise HTTPException(
        status_code=409,
        detail={
            "code": "idempotency_in_progress",
            "message": (
                "A request with this "
                f"{IDEMPOTENCY_HEADER} is already being processed; retry shortly"
            ),
        },
    )


def _record_failure(cache: Any, cache_key: str, exc: HTTPException) -> None:
    """Remember a client-visible failure so a retry replays it, not re-runs it.

    A 4xx (except 429, which is a throttle, not a verdict) is the request's
    answer and is replayed under the full TTL. Anything else keeps the claim
    for the short failure TTL, so an immediate retry cannot duplicate a side
    effect that may have partially committed.
    """
    replayable = 400 <= exc.status_code < 500 and exc.status_code != 429
    if replayable:
        _store(
            cache,
            cache_key,
            {"state": "done", "status": exc.status_code, "body": {"detail": exc.detail}},
            IDEMPOTENCY_TTL_SECONDS,
        )
    else:
        _store(cache, cache_key, {"state": "failed"}, IDEMPOTENCY_FAILED_TTL_SECONDS)


# --------------------------------------------------------------- ETag ----


def document_etag(document: dict[str, Any]) -> str:
    """A strong ETag for a JSON document (stable across process restarts)."""
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return '"' + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16] + '"'


def require_if_match(presented: str | None, current: str) -> None:
    """Refuse a stale ``If-Match`` with 412; absent means last-write-wins."""
    if presented is None:
        return
    candidates = {candidate.strip() for candidate in presented.split(",")}
    if current in candidates or "*" in candidates:
        return
    raise HTTPException(
        status_code=412,
        detail={
            "code": "precondition_failed",
            "message": "The resource changed since you read it; refetch and retry",
        },
    )
