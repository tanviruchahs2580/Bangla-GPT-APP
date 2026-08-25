import json
import logging
import sys


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def json_log(logger: logging.Logger, level: int, event: str, **fields) -> None:
    payload = {"event": event, **fields}
    logger.log(level, json.dumps(payload, ensure_ascii=False))
