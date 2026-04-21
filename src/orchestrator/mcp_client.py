"""MCP client wrapper.

Abstracts over stdio vs HTTP transports and translates MCP tool schemas into
the OpenAI tool-calling JSON format OpenRouter expects.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ToolBinding:
    """An MCP tool rendered in the OpenAI tool-calling shape."""

    name: str
    description: str
    parameters: dict[str, Any]

    def to_openai_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters or {"type": "object", "properties": {}},
            },
        }


class MCPGateway:
    """Holds an open MCP session and exposes its tools."""

    def __init__(self) -> None:
        self._stack = AsyncExitStack()
        self._session: ClientSession | None = None
        self._tools: list[ToolBinding] = []

    @classmethod
    async def connect_stdio(
        cls,
        command: str | None = None,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> MCPGateway:
        """Launch the MCP server as a child process and connect over stdio."""
        gateway = cls()
        params = StdioServerParameters(
            command=command or sys.executable,
            args=args or ["-m", "mcp_drive_server"],
            env=env or {**os.environ},
        )
        read, write = await gateway._stack.enter_async_context(stdio_client(params))
        session = await gateway._stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        gateway._session = session
        await gateway._load_tools()
        return gateway

    @classmethod
    async def connect_http(cls, url: str, token: str | None = None) -> MCPGateway:
        """Connect to a remote MCP server over streamable HTTP.

        Imported lazily because this transport requires additional extras and
        is only needed in production deployments (e.g. the Gandi instance).
        """
        try:
            from mcp.client.streamable_http import streamablehttp_client
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "HTTP MCP transport requires a newer `mcp` SDK with "
                "streamablehttp_client support."
            ) from exc
        gateway = cls()
        headers = {"Authorization": f"Bearer {token}"} if token else None
        read, write, _ = await gateway._stack.enter_async_context(
            streamablehttp_client(url, headers=headers)
        )
        session = await gateway._stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        gateway._session = session
        await gateway._load_tools()
        return gateway

    async def _load_tools(self) -> None:
        assert self._session is not None
        listing = await self._session.list_tools()
        self._tools = [
            ToolBinding(
                name=t.name,
                description=t.description or "",
                parameters=t.inputSchema or {"type": "object", "properties": {}},
            )
            for t in listing.tools
        ]
        logger.info("Loaded %d MCP tools: %s", len(self._tools), [t.name for t in self._tools])

    @property
    def tools(self) -> list[ToolBinding]:
        return list(self._tools)

    def openai_tools(self) -> list[dict[str, Any]]:
        return [t.to_openai_tool() for t in self._tools]

    async def call(self, name: str, arguments: dict[str, Any]) -> str:
        """Call an MCP tool and return a string payload suitable for the LLM.

        Preference order:
          1. `structuredContent` (JSON) — preserves list/dict shape precisely.
          2. Concatenation of TextContent blocks.
          3. Best-effort dump of non-text blocks.
        """
        assert self._session is not None, "MCPGateway not connected"
        result = await self._session.call_tool(name, arguments=arguments)

        structured = getattr(result, "structuredContent", None)
        if structured is not None and not result.isError:
            # FastMCP wraps bare lists/primitives as {"result": ...}; unwrap.
            if isinstance(structured, dict) and set(structured.keys()) == {"result"}:
                structured = structured["result"]
            return json.dumps(structured, ensure_ascii=False, default=str)

        chunks: list[str] = []
        for block in result.content or []:
            block_type = getattr(block, "type", None)
            if block_type == "text":
                chunks.append(getattr(block, "text", "") or "")
            else:
                try:
                    chunks.append(json.dumps(block.model_dump(), default=str))
                except Exception:
                    chunks.append(str(block))
        payload = "\n".join(c for c in chunks if c)

        if result.isError:
            return json.dumps({"error": payload or "tool error", "tool": name})
        return payload or "(no output)"

    async def aclose(self) -> None:
        await self._stack.aclose()
        self._session = None

    async def __aenter__(self) -> MCPGateway:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()


class MultiMCPGateway:
    """Aggregate several MCP connections behind the same tool-calling surface."""

    def __init__(self, gateways: list[tuple[str, MCPGateway]]) -> None:
        self._gateways = list(gateways)
        self._tools: list[ToolBinding] = []
        self._tool_index: dict[str, MCPGateway] = {}

        for server_name, gateway in self._gateways:
            for tool in gateway.tools:
                if tool.name in self._tool_index:
                    raise RuntimeError(
                        f"Duplicate MCP tool name '{tool.name}' exposed by multiple servers. "
                        "Rename or prefix one of the tools to keep dispatch unambiguous."
                    )
                self._tool_index[tool.name] = gateway
                self._tools.append(tool)
            logger.info(
                "Attached MCP server %s with tools: %s",
                server_name,
                [tool.name for tool in gateway.tools],
            )

    @property
    def tools(self) -> list[ToolBinding]:
        return list(self._tools)

    def openai_tools(self) -> list[dict[str, Any]]:
        return [tool.to_openai_tool() for tool in self._tools]

    async def call(self, name: str, arguments: dict[str, Any]) -> str:
        gateway = self._tool_index.get(name)
        if gateway is None:
            raise KeyError(f"Unknown MCP tool: {name}")
        return await gateway.call(name, arguments)

    async def aclose(self) -> None:
        for _, gateway in reversed(self._gateways):
            await gateway.aclose()

    async def __aenter__(self) -> MultiMCPGateway:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()


async def connect_from_definition(definition) -> MCPGateway:
    """Connect to a single MCP server described in config."""
    if definition.transport == "http":
        return await MCPGateway.connect_http(definition.url, token=definition.token or None)
    return await MCPGateway.connect_stdio(
        command=definition.command,
        args=definition.args,
        env={**os.environ, **definition.env},
    )


async def build_gateway(settings):
    """Build either a single gateway or a multi-gateway aggregator."""
    configs = settings.load_mcp_servers()
    if configs:
        gateways: list[tuple[str, MCPGateway]] = []
        try:
            for definition in configs:
                gateway = await connect_from_definition(definition)
                gateways.append((definition.name, gateway))
        except Exception:
            for _, gateway in reversed(gateways):
                await gateway.aclose()
            raise
        if len(gateways) == 1:
            return gateways[0][1]
        return MultiMCPGateway(gateways)

    if settings.mcp_transport == "http":
        return await MCPGateway.connect_http(
            settings.mcp_server_url, token=settings.mcp_server_token or None
        )
    return await MCPGateway.connect_stdio()
