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
    configure_observability_with_sentry,
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


def test_configure_sentry_traces_rate_follows_settings(monkeypatch) -> None:
    """SENTRY_TRACES_SAMPLE_RATE reaches sentry_sdk.init; an out-of-range
    value is clamped into [0, 1], not trusted (was hardcoded 0.1 at the
    init site -- P2, 2026-11-17 audit)."""
    captured: dict = {}
    fake = types.SimpleNamespace(init=lambda **kwargs: captured.update(kwargs))
    monkeypatch.setitem(sys.modules, "sentry_sdk", fake)

    configure_sentry(
        Settings(
            env="test",
            sentry_dsn="https://k@sentry.example.test/1",
            sentry_traces_sample_rate=0.25,
        )
    )
    assert captured["traces_sample_rate"] == 0.25

    configure_sentry(
        Settings(
            env="test",
            sentry_dsn="https://k@sentry.example.test/1",
            sentry_traces_sample_rate=2.0,
        )
    )
    assert captured["traces_sample_rate"] == 1.0

    configure_sentry(
        Settings(
            env="test",
            sentry_dsn="https://k@sentry.example.test/1",
            sentry_traces_sample_rate=-1.0,
        )
    )
    assert captured["traces_sample_rate"] == 0.0


def test_configure_sentry_traces_rate_defaults_and_fallbacks(monkeypatch) -> None:
    """The shipped default stays 0.1, and a duck-typed settings object
    without the field falls back to it instead of crashing."""
    captured: dict = {}
    fake = types.SimpleNamespace(init=lambda **kwargs: captured.update(kwargs))
    monkeypatch.setitem(sys.modules, "sentry_sdk", fake)

    configure_sentry(Settings(env="test", sentry_dsn="https://k@sentry.example.test/1"))
    assert captured["traces_sample_rate"] == 0.1

    configure_sentry(types.SimpleNamespace(sentry_dsn="https://k@sentry.example.test/1"))
    assert captured["traces_sample_rate"] == 0.1

    # a non-numeric value and a NaN fall back to the shipped default too
    configure_sentry(
        types.SimpleNamespace(
            sentry_dsn="https://k@sentry.example.test/1",
            sentry_traces_sample_rate="not-a-number",
        )
    )
    assert captured["traces_sample_rate"] == 0.1

    configure_sentry(
        types.SimpleNamespace(
            sentry_dsn="https://k@sentry.example.test/1",
            sentry_traces_sample_rate=float("nan"),
        )
    )
    assert captured["traces_sample_rate"] == 0.1


def test_configure_sentry_without_dsn_is_a_noop(monkeypatch) -> None:
    """No DSN configured: sentry_sdk.init must never run (the historical
    dev/test path -- Sentry stays entirely out of the process)."""
    calls: dict = {}

    def unexpected_init(**kwargs: object) -> None:
        calls["called"] = True

    fake = types.SimpleNamespace(init=unexpected_init)
    monkeypatch.setitem(sys.modules, "sentry_sdk", fake)

    configure_sentry(Settings(env="test"))
    assert calls == {}


def test_configure_sentry_survives_an_init_failure(monkeypatch) -> None:
    """Sentry init is best-effort: a raised error inside init is logged, not
    propagated -- a Sentry outage must not take the API or worker boot down."""

    def broken_init(**kwargs: object) -> None:
        raise RuntimeError("sentry sdk exploded")

    fake = types.SimpleNamespace(init=broken_init)
    monkeypatch.setitem(sys.modules, "sentry_sdk", fake)

    configure_sentry(Settings(env="test", sentry_dsn="https://k@sentry.example.test/1"))


def test_configure_observability_with_sentry_wires_both(monkeypatch) -> None:
    """The combined entry point (worker boot) runs logging setup AND Sentry
    init with the settings' sample rate."""
    captured: dict = {}
    fake = types.SimpleNamespace(init=lambda **kwargs: captured.update(kwargs))
    monkeypatch.setitem(sys.modules, "sentry_sdk", fake)

    configure_observability_with_sentry(
        Settings(
            env="test",
            sentry_dsn="https://k@sentry.example.test/1",
            sentry_traces_sample_rate=0.5,
        )
    )
    assert captured["dsn"] == "https://k@sentry.example.test/1"
    assert captured["traces_sample_rate"] == 0.5
    assert captured["before_send"] is scrub_sentry_event
