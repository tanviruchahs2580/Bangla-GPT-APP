"""Prometheus metrics for the API service.

Counters/histograms are registered once per process on a dedicated registry
so multiple ``create_app`` instances (tests, workers) never double-register.
"""

from prometheus_client import CollectorRegistry, Counter, Histogram

REGISTRY = CollectorRegistry(auto_describe=True)

REQUESTS_TOTAL = Counter(
    "bgpt_http_requests_total",
    "Total HTTP requests processed.",
    labelnames=["method", "path", "status"],
    registry=REGISTRY,
)

REQUEST_LATENCY_SECONDS = Histogram(
    "bgpt_http_request_duration_seconds",
    "HTTP request latency in seconds.",
    labelnames=["path"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
    registry=REGISTRY,
)

UNHANDLED_EXCEPTIONS_TOTAL = Counter(
    "bgpt_http_unhandled_exceptions_total",
    "Unhandled exceptions escaping the application.",
    labelnames=["method", "path"],
    registry=REGISTRY,
)

PII_REDACTED_TOTAL = Counter(
    "bgpt_pii_redacted_total",
    "PII spans stripped by the pre-LLM redactor before upstream egress.",
    labelnames=["kind"],
    registry=REGISTRY,
)
