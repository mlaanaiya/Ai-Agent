"""Ollama LLM client (100% free, local inference).

Ollama exposes an OpenAI-compatible ``/v1/chat/completions`` endpoint.
All inference runs locally on the host — no API key, no cost, no data
sent to third parties.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class OllamaError(RuntimeError):
    """Raised when the Ollama API returns a non-2xx response."""


@dataclass(slots=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0


@dataclass(slots=True)
class ChatResponse:
    model: str
    message: dict[str, Any]
    finish_reason: str | None
    usage: Usage = field(default_factory=Usage)
    raw: dict[str, Any] = field(default_factory=dict)


class OllamaClient:
    """Thin Ollama chat-completions client with tool-use support."""

    def __init__(
        self,
        *,
        base_url: str = "http://localhost:11434/v1",
        default_model: str = "qwen2.5:7b",
        timeout: float = 180.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._default_model = default_model
        self._owns_client = http_client is None
        self._http = http_client or httpx.AsyncClient(
            base_url=self._base_url,
            headers={"Content-Type": "application/json"},
            timeout=timeout,
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    async def __aenter__(self) -> OllamaClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    @property
    def cumulative_cost(self) -> float:
        return 0.0

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        temperature: float | None = None,
        extra: dict[str, Any] | None = None,
    ) -> ChatResponse:
        """Call /chat/completions and return the first choice."""
        payload: dict[str, Any] = {
            "model": model or self._default_model,
            "messages": messages,
        }
        if tools:
            payload["tools"] = tools
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice
        if temperature is not None:
            payload["temperature"] = temperature
        if extra:
            payload.update(extra)

        try:
            resp = await self._http.post("/chat/completions", json=payload)
        except httpx.HTTPError as exc:
            raise OllamaError(f"Ollama transport error: {exc}") from exc

        if resp.status_code >= 400:
            raise OllamaError(
                f"Ollama {resp.status_code}: {resp.text[:500]}"
            )
        data = resp.json()
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        finish_reason = choice.get("finish_reason")

        usage_raw = data.get("usage") or {}
        usage = Usage(
            prompt_tokens=int(usage_raw.get("prompt_tokens") or 0),
            completion_tokens=int(usage_raw.get("completion_tokens") or 0),
            total_tokens=int(usage_raw.get("total_tokens") or 0),
        )

        return ChatResponse(
            model=data.get("model", payload["model"]),
            message=message,
            finish_reason=finish_reason,
            usage=usage,
            raw=data,
        )
