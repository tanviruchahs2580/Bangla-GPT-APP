"""shared JSON-object extraction for the generic generator contracts."""

import json

from bangla_gpt_api.providers.base import ProviderError


def strip_code_fences(text: str) -> str:
    """Strip one JSON code fence from a raw model completion.

    String passes, not a regex: the pattern this replaces
    (``^```(?:json)?\\s*|\\s*```\\s*$``) rescanned a long whitespace run from
    every start position and took seconds on a 20 000-char completion (F-076).
    Behaviour is unchanged for fenced, half-fenced and unfenced completions.
    """
    out = text.strip()
    if out.startswith("```"):
        if "\n" in out:
            out = out.split("\n", 1)[1].strip()
        else:
            # A fence with no newline: drop the token and an optional tag.
            out = out[3:]
            if out.startswith("json"):
                out = out[4:]
            out = out.strip()
    close = out.rfind("```")
    if close >= 0 and not out[close + 3 :].strip():
        out = out[:close].rstrip()
    return out


def extract_json_object(text: str) -> dict:
    """Pull the first JSON object out of a raw completion (fences tolerated)."""
    cleaned = strip_code_fences(text)
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
