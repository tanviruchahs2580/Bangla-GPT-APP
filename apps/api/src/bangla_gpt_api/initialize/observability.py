"""Observability bootstrap — logging and Sentry.

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


def configure_sentry(settings: object) -> None:
    """Initialise Sentry when a DSN is configured (no-op otherwise).

    Silent on import failure so the app stays testable without external deps.
    """
    dsn = getattr(settings, "sentry_dsn", None)
    if not dsn:
        return
    try:
        import sentry_sdk  # type: ignore[import-untyped]

        sentry_sdk.init(
            dsn=dsn,
            environment=getattr(settings, "sentry_env", "development"),
            traces_sample_rate=0.1,
        )
    except Exception:
        logger.warning("sentry_init_failed", extra={"op": "init"}, exc_info=True)


def configure_observability_with_sentry(settings: object) -> None:
    """Combined entry point: logging + Sentry."""
    configure_observability(getattr(settings, "log_level", "INFO"))
    configure_sentry(settings)
