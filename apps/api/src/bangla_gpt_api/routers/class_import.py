"""H-13: the file half of the classroom CSV import.

``POST /teacher/classrooms/{room_id}/import`` (see ``routers/teacher.py``)
takes pasted CSV **text** as a JSON string, bounded by the request schema.
That is fine for copy-paste but wrong for a file: the browser had to read the
whole file into a JavaScript string before sending it. This module adds the
sibling route a file picker needs -- ``POST .../import-file`` with the CSV as
the request body -- so the SPA can hand a ``File`` straight to ``fetch`` and
the bytes never round-trip through a JSON string.

Design notes
------------
* **No new dependency.** The body is the raw ``text/csv`` (or
  ``application/octet-stream``) payload, read from the ASGI stream with an
  explicit byte bound, so the route works without ``python-multipart`` and a
  client cannot make the process buffer an arbitrary upload. A multipart
  variant would be a route-signature change in ``routers/teacher.py`` plus a
  runtime dependency; it is sketched in ``.audit/handoffs/r3-ws3.md``.
* **Encoding detection** covers the shapes a Bangladeshi school produces:
  UTF-8 with or without BOM (Excel's "CSV UTF-8") and UTF-16 with BOM (Excel's
  "Unicode text" export). Invalid byte sequences are a 422, never a 500.
* **One implementation.** The route decodes the bytes and delegates to the
  JSON handler, so row-level reporting, invite codes, in-file dedupe, the
  200-row cap, the tenant check and the single transaction are shared by
  construction rather than reimplemented.
"""

from __future__ import annotations

import codecs

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from bangla_gpt_api.routers._error_contract import AUTH_GUARD_RESPONSES
from bangla_gpt_api.routers._http_semantics import (
    IdempotencyKeyHeader,
    run_once,
    validate_idempotency_key,
)
from bangla_gpt_api.routers.teacher import classroom_import
from bangla_gpt_api.schemas import CLASS_IMPORT_MAX_CHARS, ClassImportIn, ClassImportOut

from .deps import Ctx, DbSession, TeacherOrAdminUser

router = APIRouter(responses=AUTH_GUARD_RESPONSES)

#: Byte ceiling for the upload. ``csv_text`` is capped at 20,000 *characters*
#: on the JSON path; at four UTF-8 bytes per character (the worst case for
#: Bangla, three bytes, plus slack) this is the same ceiling expressed in
#: bytes, so both paths accept the same files. It is also the point past which
#: the read stops, independent of the app-wide 4 MB body cap.
IMPORT_MAX_BYTES = CLASS_IMPORT_MAX_CHARS * 4

#: Content types a browser or Excel actually produces for a CSV file.
#: ``text/plain`` is what many systems sniff; ``application/vnd.ms-excel`` is
#: what Windows Excel puts on a "CSV (Comma delimited)" file; Safari on iOS
#: sends ``application/octet-stream``.
ACCEPTED_IMPORT_CONTENT_TYPES = frozenset(
    {
        "text/csv",
        "text/plain",
        "application/csv",
        "application/vnd.ms-excel",
        "application/octet-stream",
        "",
    }
)


async def _read_bounded(request: Request) -> bytes:
    """Read the body, refusing as soon as it is over the cap (never buffers more)."""
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > IMPORT_MAX_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"file too large; max {IMPORT_MAX_BYTES} bytes",
            )
        chunks.append(chunk)
    return b"".join(chunks)


def decode_csv_bytes(raw: bytes) -> str:
    """Decode a roster file the way the serving schools export it.

    UTF-16 is only recognised by its BOM (Excel's "Unicode text" writes one);
    everything else is treated as UTF-8, with the BOM tolerated
    (``utf-8-sig``). A file that is neither raises ``UnicodeDecodeError`` and
    becomes a 422 at the route.
    """
    if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return raw.decode("utf-16")
    return raw.decode("utf-8-sig")


@router.post(
    "/teacher/classrooms/{room_id}/import-file",
    response_model=ClassImportOut,
)
async def classroom_import_file(
    room_id: int,
    request: Request,
    db: DbSession,
    teacher: TeacherOrAdminUser,
    ctx: Ctx,
    idem_header: IdempotencyKeyHeader = None,
) -> ClassImportOut | JSONResponse:
    """Bulk-enroll students from an uploaded 'name,email' CSV file.

    ``Idempotency-Key`` is supported (H-03): a retry with the same key gets the
    first response back -- invite codes included -- instead of enrolling twice.
    """
    key = validate_idempotency_key(idem_header)
    content_type = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if content_type not in ACCEPTED_IMPORT_CONTENT_TYPES:
        raise HTTPException(
            status_code=415,
            detail="send the CSV file as text/csv, text/plain or application/octet-stream",
        )
    raw = await _read_bounded(request)
    if not raw:
        raise HTTPException(status_code=422, detail="no data rows")
    try:
        text = decode_csv_bytes(raw)
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=422,
            detail="file is not UTF-8 or UTF-16 text (BOM required for UTF-16)",
        ) from exc
    if len(text) > CLASS_IMPORT_MAX_CHARS:
        # Same character contract as the JSON path; the byte cap alone would
        # let a multi-byte file through that the JSON path would refuse.
        raise HTTPException(
            status_code=413,
            detail=f"file too large; max {CLASS_IMPORT_MAX_CHARS} characters",
        )
    if not text.strip():
        raise HTTPException(status_code=422, detail="no data rows")

    # The JSON handler does the row loop (db I/O inside); off the event loop
    # for the same reason every other sync handler runs in the threadpool.
    return await run_once(
        cache=ctx.cache,
        scope="classroom_import_file",
        user_id=teacher.id,
        key=key,
        produce=lambda: run_in_threadpool(
            classroom_import,
            room_id=room_id,
            payload=ClassImportIn(csv_text=text),
            db=db,
            teacher=teacher,
        ),
        success_status=200,
    )
