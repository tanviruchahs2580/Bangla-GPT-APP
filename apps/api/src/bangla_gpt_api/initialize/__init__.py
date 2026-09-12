"""Application initialization package (ARCH-001).

Split from ``main.py`` to eliminate the god-module anti-pattern. Each submodule
owns one initialization concern:

- ``observability``  : logging configuration, Sentry bootstrap
- ``middleware_stack`` : all middleware registration (CORS, rate limit, security)
- ``dependencies``   : provider/index/tutor/DB/admin construction → AppContext
- ``lifespan``       : lifespan context with explicit params (no closure capture)
- ``schedulers``     : background scheduler loops with health monitoring
"""

from bangla_gpt_api.initialize.dependencies import build_dependencies
from bangla_gpt_api.initialize.lifespan import build_lifespan
from bangla_gpt_api.initialize.observability import (
    configure_observability,
    configure_observability_with_sentry,
)
from bangla_gpt_api.initialize.schedulers import (
    _run_digest_loop as parent_digest_loop,
)
from bangla_gpt_api.initialize.schedulers import (
    _run_weakness_loop as weakness_refresh_loop,
)

__all__ = [
    "build_dependencies",
    "build_lifespan",
    "configure_observability",
    "configure_observability_with_sentry",
    "parent_digest_loop",
    "weakness_refresh_loop",
]
