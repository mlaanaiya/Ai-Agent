"""Entry point: run the Drive MCP server over stdio.

    $ python -m mcp_drive_server
"""

from __future__ import annotations

import logging
import os
import sys

from .server import build_server


def main() -> int:
    logging.basicConfig(
        level=os.environ.get("MCP_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,  # stdout is reserved for MCP protocol traffic.
    )
    app = build_server()
    app.run()  # defaults to stdio transport
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
