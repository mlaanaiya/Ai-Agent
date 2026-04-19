"""End-to-end test of the agent loop with a fake LLM and a fake MCP gateway."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from orchestrator.agent import Agent
from orchestrator.ollama import ChatResponse, Usage


@dataclass
class FakeGateway:
    """Stand-in for MCPGateway exposing a single echo tool."""

    calls: list[tuple[str, dict[str, Any]]]

    def openai_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "echo",
                    "description": "echo back a message",
                    "parameters": {
                        "type": "object",
                        "properties": {"message": {"type": "string"}},
                        "required": ["message"],
                    },
                },
            }
        ]

    async def call(self, name: str, arguments: dict[str, Any]) -> str:
        self.calls.append((name, arguments))
        return f"echoed:{arguments.get('message', '')}"


class ScriptedLLM:
    """Returns a scripted sequence of ChatResponse objects."""

    def __init__(self, scripted: list[ChatResponse]):
        self._queue = list(scripted)
        self.requests: list[dict[str, Any]] = []

    async def chat(self, messages, model=None, tools=None, **_: Any) -> ChatResponse:  # noqa: ANN001
        self.requests.append({"messages": messages, "tools": tools})
        return self._queue.pop(0)


def _assistant_with_tool_call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    import json

    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)},
            }
        ],
    }


async def test_agent_runs_tool_then_answers() -> None:
    gateway = FakeGateway(calls=[])
    llm = ScriptedLLM(
        [
            ChatResponse(
                model="test/model",
                message=_assistant_with_tool_call("echo", {"message": "hi"}),
                finish_reason="tool_calls",
                usage=Usage(1, 1, 2, 0.0),
            ),
            ChatResponse(
                model="test/model",
                message={"role": "assistant", "content": "The tool returned: echoed:hi"},
                finish_reason="stop",
                usage=Usage(2, 2, 4, 0.0),
            ),
        ]
    )
    agent = Agent(llm=llm, mcp=gateway, system_prompt="sys", max_steps=4)  # type: ignore[arg-type]
    result = await agent.run("please echo hi")

    assert gateway.calls == [("echo", {"message": "hi"})]
    assert "echoed:hi" in result.final_text
    assert result.stopped_reason == "completed"
    assert len(result.steps) == 2
    # The second request should include the tool-result message.
    last = llm.requests[-1]["messages"]
    assert any(m.get("role") == "tool" for m in last)


async def test_agent_respects_max_steps() -> None:
    gateway = FakeGateway(calls=[])
    # Always request a tool call — the loop must give up.
    tool_call_resp = ChatResponse(
        model="test/model",
        message=_assistant_with_tool_call("echo", {"message": "x"}),
        finish_reason="tool_calls",
        usage=Usage(1, 1, 2, 0.0),
    )
    llm = ScriptedLLM([tool_call_resp, tool_call_resp, tool_call_resp])
    agent = Agent(llm=llm, mcp=gateway, system_prompt="sys", max_steps=2)  # type: ignore[arg-type]
    result = await agent.run("loop forever")
    assert result.stopped_reason == "max_steps_reached"
    assert len(result.steps) == 2
    assert gateway.calls == [("echo", {"message": "x"}), ("echo", {"message": "x"})]


async def test_agent_surfaces_tool_errors_to_llm() -> None:
    class BrokenGateway(FakeGateway):
        async def call(self, name: str, arguments: dict[str, Any]) -> str:
            raise RuntimeError("access denied")

    gateway = BrokenGateway(calls=[])
    llm = ScriptedLLM(
        [
            ChatResponse(
                model="test/model",
                message=_assistant_with_tool_call("echo", {"message": "x"}),
                finish_reason="tool_calls",
                usage=Usage(1, 1, 2, 0.0),
            ),
            ChatResponse(
                model="test/model",
                message={"role": "assistant", "content": "sorry, could not do it"},
                finish_reason="stop",
                usage=Usage(1, 1, 2, 0.0),
            ),
        ]
    )
    agent = Agent(llm=llm, mcp=gateway, system_prompt="sys", max_steps=3)  # type: ignore[arg-type]
    result = await agent.run("try it")
    assert result.stopped_reason == "completed"
    # The tool-error payload should have been forwarded to the LLM.
    last_messages = llm.requests[-1]["messages"]
    tool_msgs = [m for m in last_messages if m.get("role") == "tool"]
    assert tool_msgs and "access denied" in tool_msgs[0]["content"]


async def test_memory_records_turns() -> None:
    gateway = FakeGateway(calls=[])
    llm = ScriptedLLM(
        [
            ChatResponse(
                model="test/model",
                message={"role": "assistant", "content": "hi!"},
                finish_reason="stop",
                usage=Usage(1, 1, 2, 0.0),
            )
        ]
    )
    agent = Agent(llm=llm, mcp=gateway, system_prompt="sys")  # type: ignore[arg-type]
    await agent.run("hello")
    snap = agent.memory.snapshot()
    assert snap[0] == {"role": "system", "content": "sys"}
    assert snap[1] == {"role": "user", "content": "hello"}
    assert snap[2]["role"] == "assistant"


@pytest.mark.parametrize("bad_json", ["not json", "{"])
async def test_agent_handles_invalid_tool_arguments(bad_json: str) -> None:
    gateway = FakeGateway(calls=[])
    llm = ScriptedLLM(
        [
            ChatResponse(
                model="test/model",
                message={
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "echo", "arguments": bad_json},
                        }
                    ],
                },
                finish_reason="tool_calls",
                usage=Usage(1, 1, 2, 0.0),
            ),
            ChatResponse(
                model="test/model",
                message={"role": "assistant", "content": "done"},
                finish_reason="stop",
                usage=Usage(1, 1, 2, 0.0),
            ),
        ]
    )
    agent = Agent(llm=llm, mcp=gateway, system_prompt="sys", max_steps=3)  # type: ignore[arg-type]
    result = await agent.run("do stuff")
    # Bad arguments degrade to an empty dict; the tool is still invoked.
    assert gateway.calls == [("echo", {})]
    assert result.final_text == "done"
