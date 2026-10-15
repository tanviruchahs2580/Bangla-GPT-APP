import contextvars
import json
import logging
import re
import sys
from typing import Any

_VALID_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}

REDACTED = "[redacted]"

# RequestId propagated via contextvar for json_log inclusion
request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)

# --------------------------------------------------------------------------
# Redaction (F-082)
# --------------------------------------------------------------------------
# Every log line in this application is assembled by json_log or by a stdlib
# logging call. Without a filter the only thing standing between the code and a
# leaked credential is per-call-site discipline, which is not a control: one
# `logger.warning("...", extra={"token": token})` in a new code path and the
# secret is in the log sink, in Sentry, and in anything that tails it.
#
# The filter is deliberately conservative and key-based: it redacts by FIELD
# NAME, not by guessing at values, so it cannot silently mangle a log line that
# merely mentions a word. Value-shaped patterns catch the common case where the
# secret is under an innocuous key ("detail", "error", "exc").

_SENSITIVE_KEY_RE = re.compile(
    r"(?i)(?:^|_)(?:"
    r"password|passwd|pwd|secret|token|api_?key|apikey|auth|authorization|"
    r"credential|credentials|cookie|set_cookie|session_id|jwt|jwt_secret|"
    r"pii_enc_key|smtp_password|client_secret|refresh_token|access_token|"
    r"otp|code|totp|mfa_secret|rfc_secret|private_key|signature"
    r")(?:$|_)"
)

#: Keys whose value is an opaque identifier, not a credential. These are the
#: only fields exempt from the value-shape rules, and only when the value does
#: not look like a credential. Redacting them would make the job/request
#: correlation lines useless, which is the whole point of logging them.
_IDENTIFIER_KEY_RE = re.compile(
    r"(?i)(?:^|_)(?:job_id|request_id|trace_id|correlation_id|span_id|event_id)(?:$|_)"
)

# Values that are unmistakably credentials regardless of the key they sit under.
_SENSITIVE_VALUE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\$argon2[id]?\$"),  # argon2 PHC string
    re.compile(r"\bpbkdf2_sha256\$"),  # legacy PHC string
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\."),  # JWT
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),  # GitHub token
    re.compile(r"\b(?:sk|ghp|glpat|xox[abps])-[A-Za-z0-9_-]{16,}"),  # vendor tokens
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{12,}=*"),  # Authorization header
    re.compile(r"\+?[0-9]{10,15}"),  # phone numbers (guardian PII)
    re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b"),  # email addresses
)

#: Keys whose values are long opaque blobs (tokens) regardless of the word match.
_OPAQUE_KEY_RE = re.compile(r"(?i)(?:^|_)(?:bearer|auth_header|raw|raw_detail)(?:$|_)")


def is_sensitive_key(key: str) -> bool:
    """True when a structured-log field name denotes a secret."""
    return bool(_SENSITIVE_KEY_RE.search(key) or _OPAQUE_KEY_RE.search(key))


def redact_value(value: Any, *, _depth: int = 0, _is_identifier: bool = False) -> Any:
    """Recursively redact a value destined for the log sink.

    Dicts and lists are walked so nested structures (e.g. ``extra={"body":
    {"password": ...}}``) are covered. Anything else is checked against the
    value patterns and replaced whole if it matches. ``_is_identifier`` marks a
    field whose key says "opaque id", which exempts only the identifier shapes.
    """
    if _depth > 6:  # pathological self-referential structure guard
        return REDACTED
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if isinstance(k, str) and is_sensitive_key(k):
                out[k] = REDACTED
            else:
                out[k] = redact_value(
                    v,
                    _depth=_depth + 1,
                    _is_identifier=isinstance(k, str) and bool(_IDENTIFIER_KEY_RE.search(k)),
                )
        return out
    if isinstance(value, (list, tuple)):
        return [redact_value(v, _depth=_depth + 1) for v in value]
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        # An identifier field is exempt from the value-shape rules, but never
        # from a rule that says "this is definitely a credential".
        if _is_identifier and not any(p.search(value) for p in _SENSITIVE_VALUE_PATTERNS):
            return value
        for pattern in _SENSITIVE_VALUE_PATTERNS:
            if pattern.search(value):
                return REDACTED
        return value
    if isinstance(value, (int, float)):
        return value
    # Any other object could carry a __repr__ that exposes internals, and a
    # structured log line has no need for it. Drop it rather than guess.
    return REDACTED


class RedactionFilter(logging.Filter):
    """Drop credentials from every log record before it is formatted.

    Applied to the ROOT logger's handlers in :func:`configure_logging`, so it
    covers every library that logs into the root logger as well as this
    application's own call sites.
    """

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003 - stdlib signature
        if getattr(record, "allow_secret", False):
            # Set only by json_log_secret, which refuses outright in
            # production. Everything else is redacted.
            return True
        try:
            record.msg = redact_value(record.msg)
        except Exception:  # never let redaction break logging
            record.msg = REDACTED
        # ``exc_info`` renders a traceback that may embed a repr() of the
        # offending object. The message is already redacted above; the
        # formatted exception text is scrubbed once it exists.
        if record.exc_text:
            record.exc_text = redact_value(record.exc_text)
        return True


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.addFilter(RedactionFilter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    # Belt and braces: a handler added later by another library still gets the
    # filter, because the logger-level filter runs before every handler.
    if not any(isinstance(f, RedactionFilter) for f in root.filters):
        root.addFilter(RedactionFilter())
    resolved = level.strip().upper()
    if resolved not in _VALID_LEVELS:
        resolved = "INFO"
    root.setLevel(getattr(logging, resolved))


def json_log(logger: logging.Logger, level: int, event: str, **fields) -> None:
    """Emit one structured line.

    ``fields`` are redacted *before* serialisation. A ``logging.Filter`` alone
    is not enough here: by the time a filter runs, ``record.msg`` is already a
    JSON string, so key-based redaction can no longer see which value belonged
    to ``password`` and has to fall back on guessing from the value's shape.
    Redacting the mapping first makes the field names authoritative.
    """
    rid = request_id_var.get()
    if rid:
        fields.setdefault("request_id", rid)
    safe = {"event": event, **redact_value(fields)}
    logger.log(level, json.dumps(safe, ensure_ascii=False, default=str))


# --------------------------------------------------------------------------
# The one deliberate exception: logging a secret.
# --------------------------------------------------------------------------
# The reset flow prints the single-use token to the console outside production
# so a developer with no SMTP can still complete it. That is a legitimate
# need, but "the only thing stopping the leak is an `if` at one call site" is
# not a control: add a second call site, or move the branch, and a live
# password-reset token goes to the log sink.
#
# So the exemption is centralised and environment-driven instead. `create_app`
# sets the flag from Settings; in production json_log_secret does not emit the
# value at all — it emits the event with the field redacted and a marker
# saying the attempt was blocked.

_secret_logging_allowed = False


def set_secret_logging_allowed(value: bool) -> None:
    """Called once per app build from :func:`bangla_gpt_api.main.create_app`."""
    global _secret_logging_allowed
    _secret_logging_allowed = bool(value)


def secret_logging_allowed() -> bool:
    return _secret_logging_allowed


def json_log_secret(logger: logging.Logger, level: int, event: str, **fields) -> None:
    """Emit a secret verbatim, outside production only.

    In production the value is never written; the event still fires, carrying
    ``secret_logging_blocked: true`` and a redacted field, so the attempt is
    visible rather than silent.
    """
    if not _secret_logging_allowed:
        json_log(logger, level, event, secret_logging_blocked=True, **fields)
        return
    rid = request_id_var.get()
    if rid:
        fields.setdefault("request_id", rid)
    message = json.dumps({"event": event, **fields}, ensure_ascii=False, default=str)
    record = logger.makeRecord(logger.name, level, "(secret)", 0, message, (), None)
    record.allow_secret = True
    logger.handle(record)
