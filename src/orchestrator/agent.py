"""The agent loop.

A single `run` call:
  1. Adds the user's prompt to memory.
  2. Calls OpenRouter with the MCP-discovered tools.
  3. If the model requests tool calls, executes them via the MCP gateway,
     appends the results, and loops.
  4. Stops when the model returns a final assistant message (no tool_calls),
     when `max_steps` is hit, or when the cost budget is exceeded.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from .mcp_client import MCPGateway
from .memory import ConversationMemory
from .openrouter import BudgetExceededError, OpenRouterClient

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AgentStepTrace:
    step: int
    model: str
    finish_reason: str | None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0


@dataclass(slots=True)
class AgentResult:
    final_text: str
    steps: list[AgentStepTrace] = field(default_factory=list)
    total_cost_usd: float = 0.0
    stopped_reason: str = "completed"


class Agent:
    def __init__(
        self,
        llm: OpenRouterClient,
        mcp: MCPGateway,
        system_prompt: str,
        *,
        model: str | None = None,
        max_steps: int = 8,
    ) -> None:
        self._llm = llm
        self._mcp = mcp
        self._memory = ConversationMemory(system_prompt=system_prompt)
        self._model = model
        self._max_steps = max_steps

    @property
    def memory(self) -> ConversationMemory:
        return self._memory

    async def run(self, user_prompt: str) -> AgentResult:
        """Run the agent loop and return only the final AgentResult.

        Implemented on top of `stream_events` so both paths share the exact
        same behavior.
        """
        result = AgentResult(final_text="")
        async for event in self.stream_events(user_prompt):
            if event["type"] == "step":
                result.steps.append(event["trace"])
                result.total_cost_usd += event["trace"].cost_usd
            elif event["type"] == "final":
                result.final_text = event["text"]
                result.stopped_reason = event["stopped_reason"]
        return result

    async def stream_events(self, user_prompt: str) -> AsyncIterator[dict[str, Any]]:
        """Run the agent loop, yielding structured events as they happen.

        Event schema (all events carry `type`):
            {"type": "user",           "text": str}
            {"type": "llm_start",      "step": int}
            {"type": "assistant",      "step": int, "text": str | None,
                                        "tool_calls": [ {id,name,arguments}, ... ]}
            {"type": "tool_call",      "step": int, "id": str, "name": str,
                                        "arguments": dict}
            {"type": "tool_result",    "step": int, "id": str, "name": str,
                                        "content": str, "error": bool}
            {"type": "step",           "trace": AgentStepTrace}
            {"type": "final",          "text": str, "stopped_reason": str,
                                        "total_cost_usd": float}
        """
        self._memory.add_user(user_prompt)
        yield {"type": "user", "text": user_prompt}
        tools = self._mcp.openai_tools()
        total_cost = 0.0

        for step in range(1, self._max_steps + 1):
            yield {"type": "llm_start", "step": step}
            try:
                response = await self._llm.chat(
                    messages=self._memory.snapshot(),
                    model=self._model,
                    tools=tools or None,
                )
            except BudgetExceededError as exc:
                yield {
                    "type": "final",
                    "text": f"Budget exceeded: {exc}",
                    "stopped_reason": f"budget_exceeded: {exc}",
                    "total_cost_usd": total_cost,
                }
                return

            message = response.message
            self._memory.add_assistant(message)

            trace = AgentStepTrace(
                step=step,
                model=response.model,
                finish_reason=response.finish_reason,
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                cost_usd=response.usage.total_cost_usd,
            )
            total_cost += response.usage.total_cost_usd

            raw_tool_calls = message.get("tool_calls") or []
            parsed_calls: list[dict[str, Any]] = []
            for tc in raw_tool_calls:
                tc_id = tc.get("id", "")
                fn = tc.get("function") or {}
                name = fn.get("name", "")
                raw_args = fn.get("arguments") or "{}"
                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                except json.JSONDecodeError:
                    args = {}
                    logger.warning("Tool %s: invalid JSON arguments %r", name, raw_args)
                parsed_calls.append({"id": tc_id, "name": name, "arguments": args})
            trace.tool_calls = parsed_calls

            yield {
                "type": "assistant",
                "step": step,
                "text": message.get("content"),
                "tool_calls": parsed_calls,
                "model": response.model,
                "cost_usd": response.usage.total_cost_usd,
            }

            if not parsed_calls:
                yield {"type": "step", "trace": trace}
                yield {
                    "type": "final",
                    "text": message.get("content") or "",
                    "stopped_reason": "completed",
                    "total_cost_usd": total_cost,
                }
                return

            for call in parsed_calls:
                yield {
                    "type": "tool_call",
                    "step": step,
                    "id": call["id"],
                    "name": call["name"],
                    "arguments": call["arguments"],
                }
                try:
                    tool_output = await self._mcp.call(call["name"], call["arguments"])
                    is_error = False
                except Exception as exc:  # noqa: BLE001
                    tool_output = json.dumps(
                        {"error": f"{type(exc).__name__}: {exc}", "tool": call["name"]}
                    )
                    is_error = True
                    logger.exception("Tool %s failed", call["name"])

                self._memory.add_tool_result(
                    tool_call_id=call["id"], name=call["name"], content=tool_output
                )
                yield {
                    "type": "tool_result",
                    "step": step,
                    "id": call["id"],
                    "name": call["name"],
                    "content": tool_output,
                    "error": is_error,
                }

            yield {"type": "step", "trace": trace}

        # max_steps reached without a final assistant-only message
        last = next(
            (m for m in reversed(self._memory.messages) if m.get("role") == "assistant"),
            None,
        )
        yield {
            "type": "final",
            "text": (last or {}).get("content") or "",
            "stopped_reason": "max_steps_reached",
            "total_cost_usd": total_cost,
        }
