"""Short-term conversation memory.

The orchestrator is stateless-per-call today; `ConversationMemory` holds the
OpenAI-style message list for a single session. A persistent backend can be
swapped in later without touching the agent loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ConversationMemory:
    system_prompt: str
    messages: list[dict[str, Any]] = field(default_factory=list)

    def snapshot(self) -> list[dict[str, Any]]:
        """Return the full message list including the system prompt."""
        return [{"role": "system", "content": self.system_prompt}, *self.messages]

    def add_user(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})

    def add_assistant(self, message: dict[str, Any]) -> None:
        # `message` is the raw OpenAI-style assistant message (possibly with
        # tool_calls). Store it verbatim so the next turn is valid.
        self.messages.append({"role": "assistant", **{k: v for k, v in message.items() if k != "role"}})

    def add_tool_result(self, tool_call_id: str, name: str, content: str) -> None:
        self.messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "name": name,
                "content": content,
            }
        )

    def clear(self) -> None:
        self.messages.clear()
