"""F-043 / PRIV-08: Sentry events are scrubbed before they leave the process.

The API initialised Sentry without ``before_send``, so an exception message
quoting a reset token, a guardian phone or a student email left the deployment
verbatim. The hook reuses ``logging_config.redact_value`` -- the same redactor
every log line already passes through -- instead of a second, drifting copy.
"""

import sys
import types

from bangla_gpt_api.config import Settings
from bangla_gpt_api.initialize.observability import (
    configure_sentry,
    scrub_sentry_event,
)
from bangla_gpt_api.logging_config import REDACTED


def test_scrub_sentry_event_redacts_known_pii_shapes() -> None:
    event = {
        "message": "password reset for kid@example.com failed",
        "extra": {"note": "call 01898765432", "count": 3},
        "exception": {
            "values": [
                {
                    "type": "ValueError",
                    "value": "token Bearer abcdefghijklmnopqrstuvwxyz",
                }
            ]
        },
        "breadcrumbs": [{"message": "reset token: sk-abcdefghijklmnopqrstuvwx"}],
    }
    scrubbed = scrub_sentry_event(event, {"exc_info": None})

    assert scrubbed["message"] == REDACTED, "the email-bearing message must not pass"
    assert scrubbed["extra"]["note"] == REDACTED, "the phone number must not pass"
    assert scrubbed["extra"]["count"] == 3, "non-PII primitives survive"
    assert scrubbed["exception"]["values"][0]["type"] == "ValueError"
    assert scrubbed["exception"]["values"][0]["value"] == REDACTED
    assert scrubbed["breadcrumbs"][0]["message"] == REDACTED


def test_scrub_sentry_event_drops_unserialisable_objects() -> None:
    class Sneaky:
        def __repr__(self) -> str:
            return "password=hunter2"

    scrubbed = scrub_sentry_event({"extra": {"obj": Sneaky()}})
    assert scrubbed["extra"]["obj"] == REDACTED


def test_configure_sentry_passes_the_hook(monkeypatch) -> None:
    captured: dict = {}
    fake = types.SimpleNamespace(init=lambda **kwargs: captured.update(kwargs))
    monkeypatch.setitem(sys.modules, "sentry_sdk", fake)

    configure_sentry(Settings(env="test", sentry_dsn="https://k@sentry.example.test/1"))

    assert captured["dsn"] == "https://k@sentry.example.test/1"
    assert captured["before_send"] is scrub_sentry_event
