"""Telegram webhook helpers for the FastAPI app."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from typing import Any

import httpx

from orchestrator.config import OrchestratorSettings

from .session_store import SessionStore


class TelegramBotError(RuntimeError):
    """Raised when a Telegram API call fails."""


class TelegramBotClient:
    """Small async wrapper around the Telegram Bot API."""

    def __init__(
        self,
        token: str,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if not token:
            raise ValueError("TELEGRAM_BOT_TOKEN is required.")
        self._owns_client = http_client is None
        self._http = http_client or httpx.AsyncClient(
            base_url=f"https://api.telegram.org/bot{token}",
            timeout=20.0,
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    async def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        reply_to_message_id: int | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }
        if reply_to_message_id is not None:
            payload["reply_to_message_id"] = reply_to_message_id
        response = await self._http.post("/sendMessage", json=payload)
        if response.status_code >= 400:
            raise TelegramBotError(
                f"Telegram sendMessage failed with {response.status_code}: {response.text[:500]}"
            )


async def process_telegram_update(
    *,
    store: SessionStore,
    settings: OrchestratorSettings,
    update: dict[str, Any],
    bot_client: TelegramBotClient | None = None,
) -> dict[str, Any]:
    """Validate and process one Telegram update."""
    message = update.get("message") or update.get("edited_message") or {}
    chat = message.get("chat") or {}
    sender = message.get("from") or {}
    text = (message.get("text") or "").strip()
    chat_id = chat.get("id")
    message_id = message.get("message_id")
    user_id = sender.get("id")
    chat_type = chat.get("type") or ""

    if not chat_id or not user_id:
        return {"accepted": False, "reason": "missing chat or sender id"}

    owns_client = bot_client is None
    bot_client = bot_client or TelegramBotClient(settings.telegram_bot_token)

    try:
        if not _is_authorized(settings, user_id=user_id, chat_id=chat_id, chat_type=chat_type):
            await bot_client.send_message(
                chat_id,
                "Acces refuse. Cet agent Telegram n'est pas autorise pour cet identifiant.",
                reply_to_message_id=message_id,
            )
            return {"accepted": False, "reason": "unauthorized"}

        if not text:
            await bot_client.send_message(
                chat_id,
                "Envoyez un message texte pour interagir avec l'agent.",
                reply_to_message_id=message_id,
            )
            return {"accepted": False, "reason": "no_text"}

        session = await store.get_or_create_by_key(
            f"telegram:{chat_id}",
            title=f"Telegram {chat_id}",
        )

        if text in {"/start", "/help"}:
            await bot_client.send_message(
                chat_id,
                "Agent actif. Envoyez votre demande en texte libre. "
                "Commandes: /reset pour vider la memoire de session.",
                reply_to_message_id=message_id,
            )
            return {"accepted": True, "reason": "help"}

        if text == "/reset":
            session.agent.memory.clear()
            session.transcript.clear()
            session.total_cost_usd = 0.0
            await bot_client.send_message(
                chat_id,
                "Memoire de session reinitialisee.",
                reply_to_message_id=message_id,
            )
            return {"accepted": True, "reason": "reset"}

        final_text = ""
        stopped_reason = "completed"
        total_cost = 0.0

        async with session.lock:
            async for event in session.agent.stream_events(text):
                payload = _event_payload(event)
                session.transcript.append(payload)
                if event["type"] == "final":
                    final_text = event.get("text") or ""
                    stopped_reason = event.get("stopped_reason") or "completed"
                    total_cost = float(event.get("total_cost_usd") or 0.0)
                    session.total_cost_usd += total_cost

        reply = final_text.strip() or "Aucune reponse exploitable n'a ete produite."
        if stopped_reason != "completed":
            reply = f"{reply}\n\n[etat: {stopped_reason}]"
        for chunk in _chunk_text(reply):
            await bot_client.send_message(
                chat_id,
                chunk,
                reply_to_message_id=message_id,
            )
        return {"accepted": True, "reason": "processed", "cost_usd": round(total_cost, 6)}
    finally:
        if owns_client:
            await bot_client.aclose()


def validate_telegram_secret(
    settings: OrchestratorSettings,
    header_value: str | None,
) -> bool:
    expected = settings.telegram_webhook_secret.strip()
    if not expected:
        return True
    return bool(header_value) and header_value == expected


def _is_authorized(
    settings: OrchestratorSettings,
    *,
    user_id: int,
    chat_id: int,
    chat_type: str,
) -> bool:
    if not settings.telegram_allowed_user_ids and not settings.telegram_allowed_chat_ids:
        return False
    if settings.telegram_require_private_chat and chat_type != "private":
        return False
    if settings.telegram_allowed_user_ids and user_id not in settings.telegram_allowed_user_ids:
        return False
    if settings.telegram_allowed_chat_ids and chat_id not in settings.telegram_allowed_chat_ids:
        return False
    return True


def _default_json(obj: Any) -> Any:
    if is_dataclass(obj):
        return asdict(obj)
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    return str(obj)


def _event_payload(event: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(event, default=_default_json))


def _chunk_text(text: str, size: int = 3500) -> list[str]:
    if len(text) <= size:
        return [text]
    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= size:
            chunks.append(remaining)
            break
        split_at = remaining.rfind("\n", 0, size)
        if split_at <= 0:
            split_at = size
        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()
    return chunks
