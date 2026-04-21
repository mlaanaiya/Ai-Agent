"""Tests for Telegram webhook processing."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from orchestrator.agent import AgentStepTrace
from orchestrator.config import OrchestratorSettings
from web.telegram import process_telegram_update, validate_telegram_secret


@dataclass
class FakeBotClient:
    messages: list[dict[str, Any]] = field(default_factory=list)

    async def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        reply_to_message_id: int | None = None,
    ) -> None:
        self.messages.append(
            {
                "chat_id": chat_id,
                "text": text,
                "reply_to_message_id": reply_to_message_id,
            }
        )


class FakeAgent:
    def __init__(self) -> None:
        self.memory = type("Memory", (), {"clear": lambda self: None})()

    async def stream_events(self, user_prompt: str):
        yield {"type": "user", "text": user_prompt}
        yield {"type": "llm_start", "step": 1}
        yield {
            "type": "step",
            "trace": AgentStepTrace(
                step=1,
                model="fake",
                finish_reason="stop",
                prompt_tokens=1,
                completion_tokens=1,
                cost_usd=0.0,
            ),
        }
        yield {
            "type": "final",
            "text": "Réponse agent",
            "stopped_reason": "completed",
            "total_cost_usd": 0.001,
        }


@dataclass
class FakeSession:
    agent: FakeAgent
    transcript: list[dict[str, Any]] = field(default_factory=list)
    total_cost_usd: float = 0.0

    def __post_init__(self) -> None:
        import asyncio

        self.lock = asyncio.Lock()


class FakeStore:
    def __init__(self) -> None:
        self.keys: list[str] = []
        self.session = FakeSession(agent=FakeAgent())

    async def get_or_create_by_key(self, external_key: str, *, title: str | None = None) -> FakeSession:
        self.keys.append(external_key)
        return self.session


def _settings() -> OrchestratorSettings:
    return OrchestratorSettings(
        TELEGRAM_BOT_TOKEN="test-token",
        TELEGRAM_WEBHOOK_SECRET="secret",
        TELEGRAM_ALLOWED_USER_IDS="42",
    )


def _update(text: str, *, user_id: int = 42, chat_id: int = 1001) -> dict[str, Any]:
    return {
        "update_id": 1,
        "message": {
            "message_id": 99,
            "text": text,
            "chat": {"id": chat_id, "type": "private"},
            "from": {"id": user_id, "first_name": "Ada"},
        },
    }


async def test_process_telegram_update_runs_agent_and_replies() -> None:
    store = FakeStore()
    bot = FakeBotClient()
    result = await process_telegram_update(
        store=store,
        settings=_settings(),
        update=_update("Bonjour"),
        bot_client=bot,  # type: ignore[arg-type]
    )
    assert result["accepted"] is True
    assert store.keys == ["telegram:1001"]
    assert bot.messages[0]["text"] == "Réponse agent"
    assert store.session.total_cost_usd == 0.001


async def test_process_telegram_update_rejects_unauthorized_user() -> None:
    store = FakeStore()
    bot = FakeBotClient()
    result = await process_telegram_update(
        store=store,
        settings=_settings(),
        update=_update("Bonjour", user_id=7),
        bot_client=bot,  # type: ignore[arg-type]
    )
    assert result["accepted"] is False
    assert "Acces refuse" in bot.messages[0]["text"]


def test_validate_telegram_secret() -> None:
    settings = _settings()
    assert validate_telegram_secret(settings, "secret") is True
    assert validate_telegram_secret(settings, "wrong") is False
