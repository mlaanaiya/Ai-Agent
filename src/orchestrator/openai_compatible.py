"""OpenAI-compatible chat-completions client.

Supports OpenAI directly and any compatible provider exposing
`/chat/completions` with the OpenAI tool-calling schema.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx


class OpenAICompatibleError(RuntimeError):
    """Raised when the upstream API returns a non-2xx response."""


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


class OpenAICompatibleClient:
    """Thin async client for OpenAI-style chat completion endpoints."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.openai.com/v1",
        default_model: str = "gpt-4.1-mini",
        timeout: float = 120.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("An API key is required for the OpenAI-compatible backend.")
        self._base_url = base_url.rstrip("/")
        self._default_model = default_model
        self._owns_client = http_client is None
        self._http = http_client or httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    async def __aenter__(self) -> OpenAICompatibleClient:
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
            raise OpenAICompatibleError(f"LLM transport error: {exc}") from exc

        if resp.status_code >= 400:
            raise OpenAICompatibleError(f"LLM {resp.status_code}: {resp.text[:500]}")

        data = resp.json()
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        finish_reason = choice.get("finish_reason")
        usage_raw = data.get("usage") or {}

        return ChatResponse(
            model=data.get("model", payload["model"]),
            message=message,
            finish_reason=finish_reason,
            usage=Usage(
                prompt_tokens=int(usage_raw.get("prompt_tokens") or 0),
                completion_tokens=int(usage_raw.get("completion_tokens") or 0),
                total_tokens=int(usage_raw.get("total_tokens") or 0),
            ),
            raw=data,
        )
