"""Run the web UI with uvicorn.

    $ python -m web                    # http://127.0.0.1:8000
    $ HOST=0.0.0.0 PORT=8080 python -m web
"""

from __future__ import annotations

import logging
import os

import uvicorn

from orchestrator.config import OrchestratorSettings

from .app import create_app


def main() -> int:
    settings = OrchestratorSettings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(
        create_app(settings),
        host=host,
        port=port,
        log_level=settings.log_level.lower(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
