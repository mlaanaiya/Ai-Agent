"""Append-only JSONL audit log for every MCP tool call.

Each record captures who called what, with which arguments, and what the
outcome was. The log is append-only and flushed on every write so a crash
does not lose recent events.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class AuditLogger:
    """Thread-safe JSONL audit logger."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def record(
        self,
        *,
        tool: str,
        arguments: dict[str, Any],
        status: str,
        duration_ms: float,
        error: str | None = None,
        result_summary: dict[str, Any] | None = None,
    ) -> None:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "pid": os.getpid(),
            "tool": tool,
            "arguments": arguments,
            "status": status,
            "duration_ms": round(duration_ms, 2),
        }
        if error:
            entry["error"] = error
        if result_summary:
            entry["result"] = result_summary
        line = json.dumps(entry, ensure_ascii=False, default=str)
        with self._lock, self._path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
            fh.flush()
