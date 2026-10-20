"""``python -m bangla_gpt_api`` and the ``bgpt-api`` console script (D-12).

A thin uvicorn launcher so the packaged app has the entry point the packaging
clause promises. It must stay interchangeable with the documented command
(``python -m uvicorn bangla_gpt_api.main:app``): host and port come from the
environment (``BGPT_BIND_HOST`` / ``BGPT_BIND_PORT``) with the same localhost
default uvicorn itself uses, and every other knob keeps coming from the
``BANGLA_GPT_*`` settings the application reads at startup.
"""

from __future__ import annotations

import os


def main() -> None:
    """Run the API under uvicorn (blocking)."""
    import uvicorn

    uvicorn.run(
        "bangla_gpt_api.main:app",
        host=os.getenv("BGPT_BIND_HOST", "127.0.0.1"),
        port=int(os.getenv("BGPT_BIND_PORT", "8000")),
    )


if __name__ == "__main__":
    main()
