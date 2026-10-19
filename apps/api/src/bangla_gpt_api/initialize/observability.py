"""Observability bootstrap — logging, Sentry and tracing.

Separate from ``create_app`` so both production and test paths can configure
logging before any dependency is constructed.
"""

import logging

logger = logging.getLogger(__name__)


def configure_observability(log_level: str = "INFO") -> None:
    """Configure root logging and optional Sentry.

    Mirrors the inline logic from the old ``main.py`` so that every test or
    worker gets identical logging behaviour.
    """
    from bangla_gpt_api.logging_config import configure_logging

    configure_logging(log_level)


def configure_tracing(settings: object) -> bool:
    """Install the OpenTelemetry tracer provider (I-03 / AUD-HI-04).

    Delegates to :mod:`bangla_gpt_api.tracing`, which is a no-op unless
    ``TRACING_ENABLED`` is set; the OTLP exporter additionally needs an
    endpoint. Returns True when spans are being recorded.
    """
    from bangla_gpt_api import tracing

    return tracing.configure_tracing(settings)


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
        )
    except Exception:
        logger.warning("sentry_init_failed", extra={"op": "init"}, exc_info=True)


def configure_observability_with_sentry(settings: object) -> None:
    """Combined entry point: logging + Sentry + tracing."""
    configure_observability(getattr(settings, "log_level", "INFO"))
    configure_sentry(settings)
    configure_tracing(settings)
