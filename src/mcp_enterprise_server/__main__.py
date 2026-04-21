"""Entry point: run the enterprise MCP server over stdio."""

from __future__ import annotations

import logging
import os
import sys

from .server import build_server


def main() -> int:
    logging.basicConfig(
        level=os.environ.get("MCP_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    app = build_server()
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
