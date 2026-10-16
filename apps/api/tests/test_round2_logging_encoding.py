"""F-131: a Bengali log line must never be lost.

Observed running this project's own API on Windows: a teacher
content-generation request logged ``ai_chapter: "গণনা"`` and the handler
raised UnicodeEncodeError inside StreamHandler.emit. The logging module
swallows that and writes a "Logging error" traceback to stderr, so the
record was gone and the traceback was all that survived.

The handler cannot be subclassed to fix this -- StreamHandler.emit
catches its own exceptions and calls handleError -- so the fix is at the
stream, where the write actually happens.
"""

from __future__ import annotations

import io
import json
import logging
import sys

import pytest

from bangla_gpt_api.logging_config import (
    RedactionFilter,
    _EncodingSafeStream,
    _utf8_stream,
    configure_logging,
    json_log,
)

BENGALI = "গণনা"  # ganona (arithmetic) - a real chapter title
BENGALI_SENTENCE = "শিক্ষার্থীর প্রশ্ন: অঙ্ক ৮ ও ৫ এর যোগফল কত?"


class _CodedStream(io.StringIO):
    """A stream that encodes as cp1252 and raises on Bengali, like Windows."""

    encoding = "cp1252"

    def write(self, s):  # noqa: D102 - test double
        s.encode("cp1252")  # raises UnicodeEncodeError on Bengali
        return super().write(s)


def _record(msg: str) -> logging.LogRecord:
    return logging.LogRecord("t", logging.INFO, __file__, 1, msg, (), None)


def _emit_to(stream, msg: str) -> str:
    handler = logging.StreamHandler(_EncodingSafeStream(stream))
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.emit(_record(msg))
    return stream.getvalue()


def test_a_cp1252_stream_would_lose_a_bengali_line() -> None:
    """Non-vacuity: prove the failure the fix exists to prevent."""
    stream = _CodedStream()
    with pytest.raises(UnicodeEncodeError):
        stream.write(BENGALI)


def test_the_bengali_line_reaches_a_utf8_stream_intact() -> None:
    captured = io.StringIO()
    out = _emit_to(captured, f"chapter={BENGALI} question={BENGALI_SENTENCE}")
    assert BENGALI in out, out
    assert BENGALI_SENTENCE in out, out


def test_an_unencodable_stream_gets_an_escaped_line_not_silence() -> None:
    stream = _CodedStream()
    out = _emit_to(stream, f"chapter={BENGALI}")
    assert "chapter=" in out, out
    assert "encoding" not in out
    # ASCII-escaped, so the cp1252 stream could actually write it, and the
    # original code points are recoverable from the escapes.
    assert out.isascii(), out
    assert "\\u0997\\u09a3\\u09a8\\u09be" in out, out


def test_utf8_stream_helper_upgrades_a_configurable_stream() -> None:
    buf = io.BytesIO()
    stream = io.TextIOWrapper(buf, encoding="cp1252")
    assert stream.encoding.lower().replace("-", "") == "cp1252"
    out = _utf8_stream(stream)
    assert out.encoding.lower().replace("-", "") == "utf8"
    out.write(BENGALI)
    out.flush()
    assert BENGALI in buf.getvalue().decode("utf-8")


def test_utf8_stream_helper_leaves_a_plain_stream_alone() -> None:
    stream = io.StringIO()
    assert _utf8_stream(stream) is stream


def test_configure_logging_installs_the_safe_stream_and_the_filter() -> None:
    root = logging.getLogger()
    before = list(root.handlers)
    try:
        configure_logging("INFO")
        assert root.handlers
        handler = root.handlers[0]
        assert isinstance(handler.stream, _EncodingSafeStream)
        assert any(isinstance(f, RedactionFilter) for f in handler.filters)
    finally:
        root.handlers.clear()
        root.handlers.extend(before)


def test_encoding_safety_and_redaction_compose() -> None:
    """The two fixes must hold together: Bengali readable, secret gone."""
    captured = io.StringIO()
    handler = logging.StreamHandler(_EncodingSafeStream(captured))
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.addFilter(RedactionFilter())
    logger = logging.getLogger("test.compose")
    logger.handlers.clear()
    logger.propagate = False
    logger.addHandler(handler)
    try:
        # json_log redacts the MAPPING before serialising, which is the only
        # place the field names are still visible.
        json_log(logger, logging.INFO, "chapter", chapter=BENGALI, password="hunter2")
    finally:
        logger.handlers.clear()
    out = captured.getvalue()
    assert BENGALI in out, out
    assert "hunter2" not in out, out
    assert "[redacted]" in out, out
    assert json.loads(out)["chapter"] == BENGALI


def _render_exception_to_string(
    logger_name: str, exc: BaseException, monkeypatch: pytest.MonkeyPatch
) -> str:
    """Run the PRODUCTION wiring (configure_logging) with stdout captured."""
    captured = io.StringIO()
    root = logging.getLogger()
    before = list(root.handlers)
    try:
        monkeypatch.setattr(sys, "stdout", captured)
        configure_logging("ERROR")
        logger = logging.getLogger(logger_name)
        try:
            raise exc
        except type(exc):
            logger.exception("unhandled_exception")
    finally:
        root.handlers.clear()
        root.handlers.extend(before)
    return captured.getvalue()


def test_logger_exception_traceback_is_redacted_in_the_rendered_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B-021: a filter scrubs exc_text too early; the formatter must redact it.

    The filter runs before Formatter.format creates record.exc_text, so a
    token inside the exception message used to reach the sink via the
    traceback of logger.exception. Assertion is on the captured handler
    output -- the rendered line -- not on record.exc_text.
    """
    out = _render_exception_to_string(
        "test.exc-redaction",
        RuntimeError("Authorization: Bearer ghp_" + "a" * 30),
        monkeypatch,
    )
    assert "unhandled_exception" in out, out
    assert "ghp_" not in out, out
    assert "[redacted]" in out, out


def test_clean_exception_traceback_still_renders(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-vacuity: redaction must not swallow every traceback."""
    out = _render_exception_to_string("test.exc-clean", RuntimeError("plain failure"), monkeypatch)
    assert "unhandled_exception" in out, out
    assert "Traceback (most recent call last)" in out, out
    assert "RuntimeError: plain failure" in out, out
