"""Tests for the multi-server MCP gateway aggregator."""

from __future__ import annotations

from orchestrator.mcp_client import MultiMCPGateway, ToolBinding


class FakeGateway:
    def __init__(self, tools: list[ToolBinding], prefix: str) -> None:
        self._tools = tools
        self.prefix = prefix

    @property
    def tools(self) -> list[ToolBinding]:
        return self._tools

    async def call(self, name: str, arguments: dict[str, object]) -> str:
        return f"{self.prefix}:{name}:{arguments.get('value', '')}"

    async def aclose(self) -> None:
        return None


async def test_multi_gateway_dispatches_to_matching_server() -> None:
    one = FakeGateway(
        [ToolBinding(name="alpha", description="a", parameters={})],
        prefix="one",
    )
    two = FakeGateway(
        [ToolBinding(name="beta", description="b", parameters={})],
        prefix="two",
    )

    gateway = MultiMCPGateway(
        [("server-one", one), ("server-two", two)]  # type: ignore[arg-type]
    )

    assert [tool.name for tool in gateway.tools] == ["alpha", "beta"]
    assert await gateway.call("alpha", {"value": "x"}) == "one:alpha:x"
    assert await gateway.call("beta", {"value": "y"}) == "two:beta:y"


def test_multi_gateway_rejects_duplicate_tool_names() -> None:
    one = FakeGateway(
        [ToolBinding(name="shared", description="a", parameters={})],
        prefix="one",
    )
    two = FakeGateway(
        [ToolBinding(name="shared", description="b", parameters={})],
        prefix="two",
    )

    try:
        MultiMCPGateway([("server-one", one), ("server-two", two)])  # type: ignore[arg-type]
    except RuntimeError as exc:
        assert "Duplicate MCP tool name" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected duplicate tool names to fail")
