"""Tests for the OpenRouter client with a mocked HTTP transport."""

from __future__ import annotations

import json

import httpx
import pytest

from orchestrator.openrouter import (
    BudgetExceededError,
    OpenRouterClient,
    OpenRouterError,
)


def _make_client(handler, *, max_cost: float = 0.0) -> OpenRouterClient:
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(
        base_url="https://openrouter.test/api/v1",
        headers={"Authorization": "Bearer test", "Content-Type": "application/json"},
        transport=transport,
    )
    return OpenRouterClient(
        api_key="test",
        base_url="https://openrouter.test/api/v1",
        default_model="test/model",
        max_cost_usd=max_cost,
        http_client=http,
    )


async def test_chat_parses_response_and_usage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode())
        assert payload["model"] == "test/model"
        assert payload["messages"][0]["role"] == "user"
        return httpx.Response(
            200,
            json={
                "model": "test/model",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "hello"},
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                    "cost": 0.0001,
                },
            },
        )

    client = _make_client(handler)
    resp = await client.chat([{"role": "user", "content": "hi"}])
    assert resp.message["content"] == "hello"
    assert resp.finish_reason == "stop"
    assert resp.usage.total_tokens == 15
    assert resp.usage.total_cost_usd == pytest.approx(0.0001)
    assert client.cumulative_cost == pytest.approx(0.0001)
    await client.aclose()


async def test_chat_raises_on_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="kaboom")

    client = _make_client(handler)
    with pytest.raises(OpenRouterError, match="500"):
        await client.chat([{"role": "user", "content": "x"}])
    await client.aclose()


async def test_budget_enforced() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "test/model",
                "choices": [
                    {"finish_reason": "stop", "message": {"role": "assistant", "content": "ok"}}
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2, "cost": 0.5},
            },
        )

    client = _make_client(handler, max_cost=0.1)
    with pytest.raises(BudgetExceededError):
        await client.chat([{"role": "user", "content": "x"}])
    await client.aclose()
