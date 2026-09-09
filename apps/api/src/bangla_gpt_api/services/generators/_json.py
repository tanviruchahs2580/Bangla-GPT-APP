"""Wave 1: shared JSON-object extraction for the generic generator contracts."""

import json
import re

from bangla_gpt_api.providers.base import ProviderError

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```\s*$")


def extract_json_object(text: str) -> dict:
    """Pull the first JSON object out of a raw completion (fences tolerated)."""
    cleaned = _FENCE_RE.sub("", text.strip())
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ProviderError("provider returned no JSON object")
    try:
        data = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ProviderError(f"invalid JSON from provider: {exc}") from exc
    if not isinstance(data, dict):
        raise ProviderError("generator payload is not an object")
    return data


def require_str(data: dict, key: str, label: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ProviderError(f"{label} key '{key}' must be a non-empty string")
    return value.strip()


def require_echo(data: dict, *, class_level: int, subject: str, label: str) -> None:
    """Validation gate: the payload must echo the requested subject/class."""
    if data.get("subject") != subject:
        raise ProviderError(f"{label} payload must echo subject {subject!r}")
    if data.get("class_level") != class_level:
        raise ProviderError(f"{label} payload must echo class_level {class_level}")
