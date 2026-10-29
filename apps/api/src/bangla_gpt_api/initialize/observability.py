"""Observability bootstrap — logging and Sentry.

Separate from ``create_app`` so both production and test paths can configure
logging before any dependency is constructed.
"""

import logging

from bangla_gpt_api.logging_config import redact_value

logger = logging.getLogger(__name__)


def configure_observability(log_level: str = "INFO") -> None:
    """Configure root logging and optional Sentry.

    Mirrors the inline logic from the old ``main.py`` so that every test or
    worker gets identical logging behaviour.
    """
    from bangla_gpt_api.logging_config import configure_logging

    configure_logging(log_level)


def scrub_sentry_event(event: dict, hint: object = None) -> dict:
    """Sentry ``before_send`` hook: run the log redactor over the event (F-043).

    Nothing filtered error payloads on the way to a third-party service: an
    exception message quoting a reset token, a guardian phone or a student
    email left the deployment as-is. ``logging_config.redact_value`` already
    knows the credential/PII field names and value shapes this codebase uses,
    so the event goes through the SAME redactor rather than a second, drifting
    copy. Unknown objects are replaced wholesale by the redactor, which also
    keeps the payload JSON-safe for Sentry.
    """
    scrubbed = redact_value(event)
    return scrubbed if isinstance(scrubbed, dict) else {}


def configure_sentry(settings: object) -> None:
    """Initialise Sentry when a DSN is configured (no-op otherwise).

    Silent on import failure so the app stays testable without external deps.
    """
    dsn = getattr(settings, "sentry_dsn", None)
    if not dsn:
        return
    try:
        import sentry_sdk

        sentry_sdk.init(
            dsn=dsn,
            environment=getattr(settings, "sentry_env", "development"),
            traces_sample_rate=0.1,
            before_send=scrub_sentry_event,
        )
    except Exception:
        logger.warning("sentry_init_failed", extra={"op": "init"}, exc_info=True)


def configure_observability_with_sentry(settings: object) -> None:
    """Combined entry point: logging + Sentry."""
    configure_observability(getattr(settings, "log_level", "INFO"))
    configure_sentry(settings)
