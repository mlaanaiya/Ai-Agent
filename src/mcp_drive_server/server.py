"""MCP server wiring: registers Drive-backed tools on an MCP stdio server.

The server is intentionally minimal — it only mediates access to the sandboxed
Drive folder. All policy decisions (sandbox, MIME allow-list, byte cap) live in
`drive.DriveClient`; this module is purely glue + audit.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from mcp.server.fastmcp import FastMCP

from .audit import AuditLogger
from .config import DriveServerSettings
from .drive import DriveClient, DriveError

logger = logging.getLogger(__name__)


def build_server(
    settings: DriveServerSettings | None = None,
    drive: DriveClient | None = None,
) -> FastMCP:
    """Construct a FastMCP app with Drive tools registered.

    Both `settings` and `drive` are optional for testability: tests inject a
    fake DriveClient and skip the validation that requires real credentials.
    """
    settings = settings or DriveServerSettings()
    if drive is None:
        settings.ensure_valid()
        drive = DriveClient(
            service_account_file=settings.service_account_file,
            root_folder_id=settings.root_folder_id,
            allowed_mime_types=settings.allowed_mime_types,
            max_read_bytes=settings.max_read_bytes,
        )
    audit = AuditLogger(settings.audit_log)

    app = FastMCP(
        name="drive-gateway",
        instructions=(
            "Sandboxed Google Drive. All operations are restricted to a single "
            "root folder. Use list_files or search_drive to discover files, "
            "read_document to fetch contents, save_file to persist results."
        ),
    )

    def _run_tool(tool: str, arguments: dict[str, Any], fn):  # type: ignore[no-untyped-def]
        start = time.perf_counter()
        try:
            result = fn()
        except DriveError as exc:
            duration = (time.perf_counter() - start) * 1000
            audit.record(
                tool=tool,
                arguments=arguments,
                status="denied",
                duration_ms=duration,
                error=str(exc),
            )
            raise
        except Exception as exc:  # noqa: BLE001 — we want to audit everything
            duration = (time.perf_counter() - start) * 1000
            audit.record(
                tool=tool,
                arguments=arguments,
                status="error",
                duration_ms=duration,
                error=f"{type(exc).__name__}: {exc}",
            )
            raise
        duration = (time.perf_counter() - start) * 1000
        summary: dict[str, Any] = {}
        if isinstance(result, list):
            summary["count"] = len(result)
        elif isinstance(result, dict):
            summary = {k: result[k] for k in ("id", "name", "size") if k in result}
        audit.record(
            tool=tool,
            arguments=arguments,
            status="ok",
            duration_ms=duration,
            result_summary=summary or None,
        )
        return result

    @app.tool(
        name="list_files",
        description=(
            "List files inside the sandbox (or inside a specific subfolder of it). "
            "Returns id, name, mime_type, size, modified_time."
        ),
    )
    def list_files(folder_id: str | None = None, query: str | None = None) -> list[dict[str, Any]]:
        return _run_tool(
            "list_files",
            {"folder_id": folder_id, "query": query},
            lambda: [f.to_dict() for f in drive.list_files(folder_id=folder_id, query=query)],
        )

    @app.tool(
        name="search_drive",
        description=(
            "Search files by name substring across the sandbox (up to 3 levels deep). "
            "Returns up to `max_results` matches."
        ),
    )
    def search_drive(query: str, max_results: int = 20) -> list[dict[str, Any]]:
        return _run_tool(
            "search_drive",
            {"query": query, "max_results": max_results},
            lambda: [f.to_dict() for f in drive.search_drive(query, max_results=max_results)],
        )

    @app.tool(
        name="read_document",
        description=(
            "Read the text content of a document inside the sandbox. "
            "Google Docs/Sheets/Slides are exported as text/CSV. "
            "Fails if the file is outside the sandbox, of a disallowed MIME type, "
            "or exceeds the configured byte cap."
        ),
    )
    def read_document(file_id: str) -> dict[str, Any]:
        return _run_tool(
            "read_document",
            {"file_id": file_id},
            lambda: drive.read_document(file_id),
        )

    @app.tool(
        name="save_file",
        description=(
            "Create a new file inside the sandbox (or a specific subfolder). "
            "`content` is UTF-8 text; `mime_type` defaults to text/plain."
        ),
    )
    def save_file(
        name: str,
        content: str,
        folder_id: str | None = None,
        mime_type: str = "text/plain",
    ) -> dict[str, Any]:
        return _run_tool(
            "save_file",
            {
                "name": name,
                "folder_id": folder_id,
                "mime_type": mime_type,
                "content_length": len(content),
            },
            lambda: drive.save_file(
                name=name, content=content, folder_id=folder_id, mime_type=mime_type
            ).to_dict(),
        )

    @app.tool(
        name="create_folder",
        description=(
            "Create a new subfolder inside the sandbox (or a specific parent folder). "
            "Returns the new folder's id/name."
        ),
    )
    def create_folder(name: str, parent_id: str | None = None) -> dict[str, Any]:
        return _run_tool(
            "create_folder",
            {"name": name, "parent_id": parent_id},
            lambda: drive.create_folder(name=name, parent_id=parent_id).to_dict(),
        )

    @app.tool(
        name="get_metadata",
        description=(
            "Get full metadata for a file: id, name, mime_type, size, modified_time, "
            "parents, web_link, description. Does NOT read the file contents."
        ),
    )
    def get_metadata(file_id: str) -> dict[str, Any]:
        return _run_tool(
            "get_metadata",
            {"file_id": file_id},
            lambda: drive.get_metadata(file_id),
        )

    @app.tool(
        name="move_file",
        description=(
            "Move a file to a different folder within the sandbox. "
            "Both the file and the destination must be inside the sandbox."
        ),
    )
    def move_file(file_id: str, new_parent_id: str) -> dict[str, Any]:
        return _run_tool(
            "move_file",
            {"file_id": file_id, "new_parent_id": new_parent_id},
            lambda: drive.move_file(file_id=file_id, new_parent_id=new_parent_id).to_dict(),
        )

    @app.tool(
        name="rename_file",
        description="Rename a file inside the sandbox.",
    )
    def rename_file(file_id: str, new_name: str) -> dict[str, Any]:
        return _run_tool(
            "rename_file",
            {"file_id": file_id, "new_name": new_name},
            lambda: drive.rename_file(file_id=file_id, new_name=new_name).to_dict(),
        )

    @app.tool(
        name="delete_file",
        description=(
            "Permanently delete a file inside the sandbox. "
            "Cannot delete the sandbox root. Use with caution."
        ),
    )
    def delete_file(file_id: str) -> dict[str, Any]:
        return _run_tool(
            "delete_file",
            {"file_id": file_id},
            lambda: drive.delete_file(file_id),
        )

    return app
