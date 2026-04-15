"""Audit logger tests."""

from __future__ import annotations

import json
from pathlib import Path

from mcp_drive_server.audit import AuditLogger


def test_audit_appends_jsonl(tmp_path: Path) -> None:
    log_path = tmp_path / "audit.jsonl"
    logger = AuditLogger(log_path)
    logger.record(
        tool="read_document",
        arguments={"file_id": "abc"},
        status="ok",
        duration_ms=12.5,
        result_summary={"id": "abc", "size": 42},
    )
    logger.record(
        tool="read_document",
        arguments={"file_id": "outside"},
        status="denied",
        duration_ms=3.2,
        error="Access denied",
    )
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    second = json.loads(lines[1])
    assert first["tool"] == "read_document"
    assert first["status"] == "ok"
    assert first["result"] == {"id": "abc", "size": 42}
    assert "ts" in first
    assert second["status"] == "denied"
    assert second["error"] == "Access denied"
