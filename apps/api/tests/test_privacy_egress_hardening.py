"""PRIV-001 / PRIV-002: the two reproduced PII egress leaks stay closed.

Both leaks were reproduced by execution before these tests existed:

* PRIV-001 -- ``services/pii.py`` recognised only the unseparated ASCII
  spelling, so ``01712-345678``, ``017 12345678``, ``(017) 12345678``,
  ``+880 1712-345678`` and every Bangla-digit number reached the upstream model
  verbatim, while ``+8801712345678`` / ``০১৭১২৩৪৫৬৭৮`` were caught only by the
  Unicode-aware NID fallback and metered under the wrong kind.
* PRIV-002 -- SQLAlchemy embeds bound parameter values in ``str(exception)``
  (``[parameters: ('আমার ফোন 01712-345678',)]``). ``middleware.py`` logs an
  unhandled DB error with ``logger.exception``, and Sentry's ``before_send``
  ships the same string. ``logging_config``'s ASCII-only value pattern let the
  hyphenated spelling through to stdout *and* to Sentry (measured 2026-11-10).

The fix's important property is that the strip lives in ``redact_value``, so
RedactionFilter, RedactingFormatter, ``json_log`` and ``scrub_sentry_event``
all inherit it from one hook. A strip inside RedactingFormatter would have
closed stdout and left Sentry leaking.
"""

import io
import json
import logging
import time

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from bangla_gpt_api.initialize.observability import scrub_sentry_event
from bangla_gpt_api.logging_config import (
    _PII_PHONE_RE,
    _PII_VALUE_PATTERNS,
    REDACTED,
    RedactingFormatter,
    RedactionFilter,
    json_log,
    redact_value,
)
from bangla_gpt_api.services.pii import _MOBILE_RE

#: The reproduced guardian number, assembled at runtime ON PURPOSE: a literal
#: in this file would also appear in a formatted traceback's source line, where
#: the conservative whole-value rule (correctly) replaces the entire message
#: and hides which mechanism did the work.
PHONE = "01712" + "-345678"


def _sqlalchemy_error() -> SQLAlchemyError:
    """A CHECK violation whose message embeds the bound parameter value."""
    engine = create_engine("sqlite://")
    try:
        with engine.connect() as conn:
            conn.execute(text("CREATE TABLE t (x TEXT CHECK (length(x) < 3))"))
            conn.execute(text("INSERT INTO t (x) VALUES (:v)"), {"v": PHONE})
    except SQLAlchemyError as exc:
        return exc
    finally:
        engine.dispose()
    raise AssertionError("the CHECK constraint did not fire")


def _capture() -> tuple[logging.Logger, io.StringIO]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(RedactingFormatter("%(message)s"))
    handler.addFilter(RedactionFilter())
    logger = logging.getLogger("priv002.egress.probe")
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger, stream


# ---------------------------------------------------------------------------
# The duplicated recogniser (PRIV-002's parity guard).
# ---------------------------------------------------------------------------


def test_log_phone_pattern_matches_the_prompt_recogniser() -> None:
    """The two copies must move together.

    ``logging_config`` cannot import ``services.pii``: it sits below services
    (``providers.base`` imports it), and the retrieval-does-not-reach-up
    import-linter contract forbids retrieval -> services. The pattern is
    therefore duplicated, and this test is the drift guard that makes a
    one-sided change to either copy fail loudly.
    """
    assert _PII_PHONE_RE.pattern == _MOBILE_RE.pattern
    assert _PII_PHONE_RE.flags == _MOBILE_RE.flags
    assert _PII_PHONE_RE in _PII_VALUE_PATTERNS


def test_phone_spellings_are_redacted_through_the_log_hook() -> None:
    """Every spelling the prompt redactor recognises is dropped by the sink too."""
    for spelling in ("01712-345678", "017 1234 5678", "+880 1712-345678", "০১৭-১২৩৪-৫৬৭৮"):
        assert redact_value({"detail": f"ফোন {spelling}"})["detail"] == REDACTED, spelling


def test_raw_unstructured_line_with_a_separated_phone_is_redacted() -> None:
    """The F-188-era conservative contract, now covering separated spellings."""
    assert redact_value("guardian called " + PHONE) == REDACTED


def test_opaque_identifier_exemption_survives_the_new_pattern() -> None:
    """F-188: a hex request id must not be re-read as a phone by the new shape."""
    assert redact_value({"request_id": "9c12968924894e25"}) == {"request_id": "9c12968924894e25"}


# ---------------------------------------------------------------------------
# The SQLAlchemy bound-parameter strip (PRIV-002).
# ---------------------------------------------------------------------------


def test_helper_strips_bound_parameters_and_keeps_the_sql_shape() -> None:
    raw = str(_sqlalchemy_error())
    assert PHONE in raw, "the fixture must reproduce the leak first"
    scrubbed = redact_value(raw)
    assert PHONE not in scrubbed
    assert "[parameters redacted]" in scrubbed
    # The diagnostic value of the error is kept: the statement and the vendor
    # hint carry no bound data.
    assert "[SQL: INSERT INTO t (x) VALUES (?)]" in scrubbed
    assert "Background on this error" in scrubbed


def test_the_strip_is_idempotent() -> None:
    scrubbed = redact_value(str(_sqlalchemy_error()))
    assert redact_value(scrubbed) == scrubbed


def test_sentry_event_carrying_the_db_error_is_stripped() -> None:
    raw = str(_sqlalchemy_error())
    event = {
        "message": f"db failure: {raw}",
        "exception": {"values": [{"type": "IntegrityError", "value": raw}]},
        "extra": {"exc": raw},
    }
    scrubbed = scrub_sentry_event(event, {"exc_info": None})
    assert scrubbed is not None
    serialized = json.dumps(scrubbed, default=str)
    assert PHONE not in serialized
    assert "[parameters redacted]" in serialized
    assert "INSERT INTO t" in serialized


def test_json_log_field_with_a_db_error_is_stripped() -> None:
    logger, stream = _capture()
    json_log(logger, logging.ERROR, "db_error", exc=str(_sqlalchemy_error()))
    payload = json.loads(stream.getvalue().strip())
    assert payload["event"] == "db_error"
    assert PHONE not in payload["exc"]
    assert "[parameters redacted]" in payload["exc"]


def test_logger_exception_traceback_carries_no_bound_parameters() -> None:
    """The exact reported path: middleware.py logs an unhandled DB error."""
    logger, stream = _capture()
    try:
        raise _sqlalchemy_error()
    except SQLAlchemyError:
        logger.exception("unhandled_exception")
    emitted = stream.getvalue()
    assert PHONE not in emitted
    assert "[parameters redacted]" in emitted
    assert "unhandled_exception" in emitted


def test_unterminated_parameters_section_is_stripped_to_end_of_line() -> None:
    """No closing bracket means parameter data continues: strip it all."""
    text = "[SQL: select 1]\n[parameters: ('" + PHONE + "'\nthis line survives"
    out = redact_value(text)
    assert PHONE not in out
    assert "[parameters redacted]" in out
    assert "this line survives" in out


def test_section_ends_at_the_last_bracket_on_the_line() -> None:
    """A list value carries inner brackets; a first-bracket scan stops inside it."""
    text = "[parameters: (['" + PHONE + "', 'x'],)]\nkeep"
    assert redact_value(text) == "[parameters redacted]\nkeep"


def test_every_section_in_a_multiline_error_is_stripped() -> None:
    text = f"[parameters: ('{PHONE}',)]\n[SQL: select 1]\n[parameters: ('ok',)]"
    out = redact_value(text)
    assert PHONE not in out
    assert out.count("[parameters redacted]") == 2


def test_a_message_containing_the_marker_is_stripped_not_scanned() -> None:
    """The marker can arrive inside attacker-influenced text; the scan is literal."""
    text = "[parameters: ('student wrote: [parameters: hello',)]\ntail"
    out = redact_value(text)
    assert "hello" not in out
    assert out.endswith("tail")


def test_non_sqlalchemy_text_is_unchanged() -> None:
    assert redact_value("cache warm-up finished in 120 ms") == "cache warm-up finished in 120 ms"
    assert redact_value("division by zero") == "division by zero"
    assert redact_value({"detail": "no marker or pii here"}) == {"detail": "no marker or pii here"}


#: 6.2 MB of the literal the scan must not backtrack over. The naive regex was
#: measured at 414 ms on a 48 000-marker field (1/10th of this one).
MARKER_RUN = "[parameters: " * 480_000


def test_repeated_marker_input_is_linear_not_backtracking() -> None:
    started = time.perf_counter()
    out = redact_value(MARKER_RUN)
    elapsed = time.perf_counter() - started
    assert out == "[parameters redacted]"
    assert elapsed < 0.5, f"{elapsed:.3f}s on {len(MARKER_RUN)} chars -- quadratic scan?"
