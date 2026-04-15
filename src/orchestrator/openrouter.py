"""Minimal OpenRouter client.

OpenRouter exposes an OpenAI-compatible `/chat/completions` endpoint, so we
speak the OpenAI tool-calling dialect and let OpenRouter route to whichever
underlying model is configured.

We intentionally do not pull in the full `openai` SDK: we only need one
endpoint and staying on `httpx` keeps the dependency surface small.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class OpenRouterError(RuntimeError):
    """Raised when the OpenRouter API returns a non-2xx response."""


class BudgetExceededError(RuntimeError):
    """Raised when an agent run exceeds its USD budget."""


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


class OpenRouterClient:
    """Thin OpenRouter chat-completions client with tool-use support."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://openrouter.ai/api/v1",
        default_model: str = "anthropic/claude-3.5-sonnet",
        app_url: str = "",
        app_name: str = "ai-agent",
        max_cost_usd: float = 0.0,
        timeout: float = 60.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("OpenRouter API key is required")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._default_model = default_model
        self._max_cost = max_cost_usd
        self._cumulative_cost = 0.0
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        if app_url:
            headers["HTTP-Referer"] = app_url
        if app_name:
            headers["X-Title"] = app_name
        self._owns_client = http_client is None
        self._http = http_client or httpx.AsyncClient(
            base_url=self._base_url,
            headers=headers,
            timeout=timeout,
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    async def __aenter__(self) -> OpenRouterClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    @property
    def cumulative_cost(self) -> float:
        return self._cumulative_cost

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
        """Call /chat/completions and return the first choice as a ChatResponse."""
        payload: dict[str, Any] = {
            "model": model or self._default_model,
            "messages": messages,
            "usage": {"include": True},  # ask OpenRouter to report cost
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
            raise OpenRouterError(f"OpenRouter transport error: {exc}") from exc

        if resp.status_code >= 400:
            raise OpenRouterError(
                f"OpenRouter {resp.status_code}: {resp.text[:500]}"
            )
        data = resp.json()
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        finish_reason = choice.get("finish_reason")

        usage_raw = data.get("usage") or {}
        cost = float(usage_raw.get("cost") or usage_raw.get("total_cost") or 0.0)
        usage = Usage(
            prompt_tokens=int(usage_raw.get("prompt_tokens") or 0),
            completion_tokens=int(usage_raw.get("completion_tokens") or 0),
            total_tokens=int(usage_raw.get("total_tokens") or 0),
            total_cost_usd=cost,
        )
        self._cumulative_cost += cost
        if self._max_cost > 0 and self._cumulative_cost > self._max_cost:
            raise BudgetExceededError(
                f"Budget of ${self._max_cost:.4f} USD exceeded "
                f"(cumulative ${self._cumulative_cost:.4f} USD)."
            )

        return ChatResponse(
            model=data.get("model", payload["model"]),
            message=message,
            finish_reason=finish_reason,
            usage=usage,
            raw=data,
        )
