import contextvars
import json
import logging
import sys

_VALID_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}

# RequestId propagated via contextvar for json_log inclusion (S0.6)
request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    resolved = level.strip().upper()
    if resolved not in _VALID_LEVELS:
        resolved = "INFO"
    root.setLevel(getattr(logging, resolved))


def json_log(logger: logging.Logger, level: int, event: str, **fields) -> None:
    rid = request_id_var.get()
    if rid:
        fields.setdefault("request_id", rid)
    payload = {"event": event, **fields}
    logger.log(level, json.dumps(payload, ensure_ascii=False))
