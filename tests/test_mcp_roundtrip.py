"""Wire up a FastMCP app with a fake Drive and talk to it from MCPGateway.

This is the highest-fidelity test in the suite: it proves that the MCP tool
registration, the FastMCP server, and the MCPGateway client agree on schemas,
arguments, and content blocks.

The test uses an in-memory MCP transport (two memory streams), so no subprocess
or network is involved.
"""

from __future__ import annotations

from typing import Any

import anyio
import pytest
from mcp import ClientSession
from mcp.shared.memory import create_connected_server_and_client_session

from mcp_drive_server.drive import DriveError, DriveFile
from mcp_drive_server.server import build_server
from mcp_drive_server.config import DriveServerSettings


class FakeDrive:
    """Drive stand-in exposing the surface DriveClient would."""

    def __init__(self) -> None:
        self.saved: list[dict[str, Any]] = []

    def list_files(self, folder_id: str | None = None, query: str | None = None):
        return [
            DriveFile(
                id="file-1",
                name="Q3-notes.txt",
                mime_type="text/plain",
                size=12,
                modified_time="2026-04-01T10:00:00Z",
                parents=[folder_id or "root-folder"],
            )
        ]

    def search_drive(self, query: str, max_results: int = 20):
        if query == "missing":
            return []
        return [
            DriveFile(
                id="file-1",
                name=f"match-{query}.txt",
                mime_type="text/plain",
                size=10,
                modified_time=None,
                parents=["root-folder"],
            )
        ]

    def read_document(self, file_id: str) -> dict[str, Any]:
        if file_id == "stray":
            raise DriveError("Access denied: file stray is outside the sandbox folder.")
        return {
            "id": file_id,
            "name": "Q3-notes.txt",
            "mime_type": "text/plain",
            "size": 12,
            "encoding": "utf-8",
            "content": "hello world!",
        }

    def save_file(self, name: str, content: str, folder_id=None, mime_type="text/plain"):
        self.saved.append(
            {"name": name, "content": content, "folder_id": folder_id, "mime_type": mime_type}
        )
        return DriveFile(
            id="new-file",
            name=name,
            mime_type=mime_type,
            size=len(content),
            modified_time=None,
            parents=[folder_id or "root-folder"],
        )


def _settings(tmp_path) -> DriveServerSettings:  # noqa: ANN001
    return DriveServerSettings(
        DRIVE_ROOT_FOLDER_ID="root-folder",
        MCP_AUDIT_LOG=str(tmp_path / "audit.jsonl"),
    )


async def _run_with_server(fake_drive: FakeDrive, settings, body):  # noqa: ANN001
    app = build_server(settings=settings, drive=fake_drive)
    # FastMCP exposes the low-level server as `_mcp_server` in current releases.
    mcp_server = app._mcp_server
    async with create_connected_server_and_client_session(mcp_server) as session:
        await body(session)


async def test_list_files_roundtrip(tmp_path) -> None:  # noqa: ANN001
    fake = FakeDrive()

    async def body(session: ClientSession) -> None:
        tools = await session.list_tools()
        names = {t.name for t in tools.tools}
        assert {"list_files", "search_drive", "read_document", "save_file"} <= names

        result = await session.call_tool("list_files", {})
        assert not result.isError
        # FastMCP exposes list results as structuredContent = {"result": [...]}.
        structured = result.structuredContent
        assert structured is not None
        files = structured["result"] if "result" in structured else structured
        assert files[0]["name"] == "Q3-notes.txt"

    await _run_with_server(fake, _settings(tmp_path), body)


async def test_read_document_denied_is_surfaced(tmp_path) -> None:  # noqa: ANN001
    fake = FakeDrive()

    async def body(session: ClientSession) -> None:
        result = await session.call_tool("read_document", {"file_id": "stray"})
        assert result.isError is True
        text = "".join(getattr(b, "text", "") for b in result.content)
        assert "outside the sandbox" in text

    await _run_with_server(fake, _settings(tmp_path), body)


async def test_gateway_call_returns_list_json(tmp_path) -> None:  # noqa: ANN001
    """Round-trip via MCPGateway.call to ensure the client unwraps structured content."""
    import json as _json

    from orchestrator.mcp_client import MCPGateway

    fake = FakeDrive()
    app = build_server(settings=_settings(tmp_path), drive=fake)

    async def body(session: ClientSession) -> None:
        gw = MCPGateway.__new__(MCPGateway)
        gw._session = session
        # Skip _load_tools; we don't need the OpenAI tool map for this test.
        payload = await gw.call("list_files", {})
        data = _json.loads(payload)
        assert isinstance(data, list)
        assert data[0]["name"] == "Q3-notes.txt"

    async with create_connected_server_and_client_session(app._mcp_server) as session:
        await body(session)


async def test_save_file_persists_and_audits(tmp_path) -> None:  # noqa: ANN001
    fake = FakeDrive()
    settings = _settings(tmp_path)

    async def body(session: ClientSession) -> None:
        result = await session.call_tool(
            "save_file", {"name": "report.txt", "content": "hello"}
        )
        assert not result.isError
        assert fake.saved == [
            {
                "name": "report.txt",
                "content": "hello",
                "folder_id": None,
                "mime_type": "text/plain",
            }
        ]

    await _run_with_server(fake, settings, body)

    audit_lines = (tmp_path / "audit.jsonl").read_text().strip().splitlines()
    assert any("save_file" in line and '"status": "ok"' in line for line in audit_lines)
