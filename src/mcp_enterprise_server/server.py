"""MCP server exposing a tightly-scoped set of enterprise tools."""

from __future__ import annotations

import time
from typing import Any

from mcp.server.fastmcp import FastMCP

from mcp_drive_server.audit import AuditLogger

from .config import EnterpriseServerSettings
from .store import EnterpriseError, EnterpriseTools


def build_server(
    settings: EnterpriseServerSettings | None = None,
    tools: EnterpriseTools | None = None,
) -> FastMCP:
    settings = settings or EnterpriseServerSettings()
    settings.ensure_valid()
    tools = tools or EnterpriseTools(
        policies_dir=settings.policies_dir,
        request_outbox=settings.request_outbox,
        max_policy_bytes=settings.max_policy_bytes,
        allowed_request_types=set(settings.allowed_request_types),
    )
    audit = AuditLogger(settings.audit_log)

    app = FastMCP(
        name="enterprise-gateway",
        instructions=(
            "Enterprise tool gateway with least-privilege access. "
            "Read approved policies, inspect queued requests, and create "
            "structured requests for downstream human processing."
        ),
    )

    def _run_tool(tool: str, arguments: dict[str, Any], fn):  # type: ignore[no-untyped-def]
        start = time.perf_counter()
        try:
            result = fn()
        except EnterpriseError as exc:
            duration = (time.perf_counter() - start) * 1000
            audit.record(
                tool=tool,
                arguments=arguments,
                status="denied",
                duration_ms=duration,
                error=str(exc),
            )
            raise
        except Exception as exc:
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
            summary = {k: result[k] for k in ("id", "status", "slug", "title") if k in result}
        audit.record(
            tool=tool,
            arguments=arguments,
            status="ok",
            duration_ms=duration,
            result_summary=summary or None,
        )
        return result

    @app.tool(
        name="enterprise_list_policies",
        description=(
            "List approved internal policies and runbooks from the whitelisted repository. "
            "Optional query filters by slug or title."
        ),
    )
    def enterprise_list_policies(query: str | None = None) -> list[dict[str, Any]]:
        return _run_tool(
            "enterprise_list_policies",
            {"query": query},
            lambda: tools.list_policies(query=query),
        )

    @app.tool(
        name="enterprise_read_policy",
        description=(
            "Read one approved internal policy by slug. "
            "Only files inside ENTERPRISE_POLICIES_DIR are accessible."
        ),
    )
    def enterprise_read_policy(slug: str) -> dict[str, Any]:
        return _run_tool(
            "enterprise_read_policy",
            {"slug": slug},
            lambda: tools.read_policy(slug),
        )

    @app.tool(
        name="enterprise_create_request",
        description=(
            "Create a structured enterprise request for human follow-up. "
            "Writes a JSON file to the outbox; it does not call external systems directly."
        ),
    )
    def enterprise_create_request(
        request_type: str,
        title: str,
        details: str,
        priority: str = "normal",
        requester: str | None = None,
    ) -> dict[str, Any]:
        return _run_tool(
            "enterprise_create_request",
            {
                "request_type": request_type,
                "title": title,
                "details_length": len(details),
                "priority": priority,
                "requester": requester,
            },
            lambda: tools.create_request(
                request_type=request_type,
                title=title,
                details=details,
                priority=priority,
                requester=requester,
            ),
        )

    @app.tool(
        name="enterprise_list_requests",
        description=(
            "List recently queued enterprise requests from the outbox. "
            "Returns metadata only, newest first."
        ),
    )
    def enterprise_list_requests(limit: int = 20) -> list[dict[str, Any]]:
        return _run_tool(
            "enterprise_list_requests",
            {"limit": limit},
            lambda: tools.list_requests(limit=limit),
        )

    return app
