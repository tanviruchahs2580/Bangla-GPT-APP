"""The log sink must stay usable while it stays redacted (F-188 root cause).

`json_log` redacts the field mapping before serialising - the only pass that can
see field names. `RedactionFilter` then re-scanned the serialised JSON string
and replaced the *whole line* with "[redacted]" whenever any value merely looked
sensitive. A hex request_id containing an 11-digit run matches the phone
pattern, so the line carrying the event name vanished from the sink operators
use to correlate a user's report with the server's trace (measured 2026-10-30:
`test_qa_auth_logging` lost one `login_failed` record in 3 of 3 orders that
produced such an id).

These tests pin both halves: structured lines survive with their event name and
ids, and their sensitive *values* are still redacted; raw, unstructured lines
keep the conservative whole-line redaction.
"""

import io
import json
import logging

from bangla_gpt_api.logging_config import (
    RedactingFormatter,
    RedactionFilter,
    json_log,
    request_id_var,
)

ID_WITH_DIGIT_RUN = "9c12968924894e25"  # 11-digit run inside a hex id


def _capture() -> tuple[logging.Logger, io.StringIO]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(RedactingFormatter("%(message)s"))
    handler.addFilter(RedactionFilter())
    logger = logging.getLogger("w2.redaction.probe")
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger, stream


def test_structured_line_survives_a_digit_run_request_id() -> None:
    logger, stream = _capture()
    token = request_id_var.set(ID_WITH_DIGIT_RUN)
    try:
        json_log(logger, logging.WARNING, "login_failed", reason="bad_credentials", failed_count=3)
    finally:
        request_id_var.reset(token)
    line = stream.getvalue().strip()
    assert line != "[redacted]"
    payload = json.loads(line)
    assert payload["event"] == "login_failed"
    assert payload["request_id"] == ID_WITH_DIGIT_RUN
    assert payload["failed_count"] == 3


def test_sensitive_value_under_its_key_is_still_redacted() -> None:
    logger, stream = _capture()
    json_log(logger, logging.INFO, "probe", password="hunter2", note="ok")
    payload = json.loads(stream.getvalue().strip())
    assert payload["event"] == "probe"
    assert payload["password"] == "[redacted]"
    assert payload["note"] == "ok"


def test_raw_line_still_gets_the_conservative_whole_line_redaction() -> None:
    # Unstructured text has no field names to trust, so the whole line goes.
    logger, stream = _capture()
    logger.warning("guardian called 01712345678 about kid@example.test")
    assert stream.getvalue().strip() == "[redacted]"


def test_raw_line_without_pii_is_untouched() -> None:
    logger, stream = _capture()
    logger.warning("cache warm-up finished in 120 ms")
    assert stream.getvalue().strip() == "cache warm-up finished in 120 ms"
