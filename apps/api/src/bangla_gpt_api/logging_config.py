import json
import logging
import sys

_VALID_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


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
    payload = {"event": event, **fields}
    logger.log(level, json.dumps(payload, ensure_ascii=False))
