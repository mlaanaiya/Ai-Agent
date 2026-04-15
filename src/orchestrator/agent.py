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
        self._memory.add_user(user_prompt)
        tools = self._mcp.openai_tools()
        result = AgentResult(final_text="")

        for step in range(1, self._max_steps + 1):
            try:
                response = await self._llm.chat(
                    messages=self._memory.snapshot(),
                    model=self._model,
                    tools=tools or None,
                )
            except BudgetExceededError as exc:
                result.stopped_reason = f"budget_exceeded: {exc}"
                break

            trace = AgentStepTrace(
                step=step,
                model=response.model,
                finish_reason=response.finish_reason,
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                cost_usd=response.usage.total_cost_usd,
            )
            result.total_cost_usd += response.usage.total_cost_usd

            message = response.message
            self._memory.add_assistant(message)

            tool_calls = message.get("tool_calls") or []
            if not tool_calls:
                result.final_text = message.get("content") or ""
                result.steps.append(trace)
                result.stopped_reason = "completed"
                return result

            for tc in tool_calls:
                tc_id = tc.get("id", "")
                fn = tc.get("function") or {}
                name = fn.get("name", "")
                raw_args = fn.get("arguments") or "{}"
                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                except json.JSONDecodeError:
                    args = {}
                    logger.warning("Tool %s: invalid JSON arguments %r", name, raw_args)

                trace.tool_calls.append({"id": tc_id, "name": name, "arguments": args})
                logger.info("Step %d: calling tool %s(%s)", step, name, args)

                try:
                    tool_output = await self._mcp.call(name, args)
                except Exception as exc:  # noqa: BLE001 — surface error back to the LLM
                    tool_output = json.dumps(
                        {"error": f"{type(exc).__name__}: {exc}", "tool": name}
                    )
                    logger.exception("Tool %s failed", name)

                self._memory.add_tool_result(tool_call_id=tc_id, name=name, content=tool_output)

            result.steps.append(trace)

        else:
            result.stopped_reason = "max_steps_reached"
            # Best-effort: use the last assistant content, if any.
            last = next(
                (m for m in reversed(self._memory.messages) if m.get("role") == "assistant"),
                None,
            )
            if last and last.get("content"):
                result.final_text = last["content"]

        return result
