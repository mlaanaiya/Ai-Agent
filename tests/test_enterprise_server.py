"""Tests for the secure enterprise MCP server."""

from __future__ import annotations

import json

from mcp import ClientSession
from mcp.shared.memory import create_connected_server_and_client_session

from mcp_enterprise_server.config import EnterpriseServerSettings
from mcp_enterprise_server.server import build_server
from mcp_enterprise_server.store import EnterpriseTools


def _settings(tmp_path):
    policies = tmp_path / "policies"
    policies.mkdir()
    (policies / "remote-access.md").write_text(
        "# Remote Access\n\nUse MFA and manager approval.\n",
        encoding="utf-8",
    )
    return EnterpriseServerSettings(
        ENTERPRISE_POLICIES_DIR=str(policies),
        ENTERPRISE_REQUEST_OUTBOX=str(tmp_path / "outbox"),
        ENTERPRISE_AUDIT_LOG=str(tmp_path / "enterprise-audit.jsonl"),
    )


async def _run_with_server(settings, body):
    tools = EnterpriseTools(
        policies_dir=settings.policies_dir,
        request_outbox=settings.request_outbox,
        max_policy_bytes=settings.max_policy_bytes,
        allowed_request_types=set(settings.allowed_request_types),
    )
    app = build_server(settings=settings, tools=tools)
    async with create_connected_server_and_client_session(app._mcp_server) as session:
        await body(session)


async def test_enterprise_policy_roundtrip(tmp_path) -> None:
    settings = _settings(tmp_path)

    async def body(session: ClientSession) -> None:
        tools = await session.list_tools()
        names = {tool.name for tool in tools.tools}
        assert {
            "enterprise_list_policies",
            "enterprise_read_policy",
            "enterprise_create_request",
            "enterprise_list_requests",
        } <= names

        listing = await session.call_tool("enterprise_list_policies", {})
        assert not listing.isError
        structured = listing.structuredContent
        rows = structured["result"] if "result" in structured else structured
        assert rows[0]["slug"] == "remote-access"

        policy = await session.call_tool("enterprise_read_policy", {"slug": "remote-access"})
        assert not policy.isError
        structured = policy.structuredContent
        data = structured["result"] if "result" in structured else structured
        assert "Use MFA" in data["content"]

    await _run_with_server(settings, body)


async def test_enterprise_create_request_and_audit(tmp_path) -> None:
    settings = _settings(tmp_path)

    async def body(session: ClientSession) -> None:
        result = await session.call_tool(
            "enterprise_create_request",
            {
                "request_type": "access",
                "title": "VPN access for contractor",
                "details": "Need temporary access for 14 days.",
                "priority": "high",
                "requester": "telegram:12345",
            },
        )
        assert not result.isError

        queued = await session.call_tool("enterprise_list_requests", {"limit": 5})
        assert not queued.isError
        structured = queued.structuredContent
        rows = structured["result"] if "result" in structured else structured
        assert rows[0]["request_type"] == "access"
        assert rows[0]["priority"] == "high"

    await _run_with_server(settings, body)

    outbox_files = list((tmp_path / "outbox").glob("*.json"))
    assert len(outbox_files) == 1
    payload = json.loads(outbox_files[0].read_text(encoding="utf-8"))
    assert payload["status"] == "queued"

    audit_lines = (tmp_path / "enterprise-audit.jsonl").read_text(encoding="utf-8").splitlines()
    assert any("enterprise_create_request" in line and '"status": "ok"' in line for line in audit_lines)
