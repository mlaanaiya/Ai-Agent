"""Tests for the Gemini client with a mocked HTTP transport."""

from __future__ import annotations

import json

import httpx
import pytest

from orchestrator.gemini import GeminiClient, GeminiError


def _make_client(handler) -> GeminiClient:
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        headers={
            "Authorization": "Bearer test-key",
            "Content-Type": "application/json",
        },
        transport=transport,
    )
    return GeminiClient(
        api_key="test-key",
        default_model="gemini-2.0-flash",
        http_client=http,
    )


async def test_chat_parses_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode())
        assert payload["model"] == "gemini-2.0-flash"
        return httpx.Response(
            200,
            json={
                "model": "gemini-2.0-flash",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "hello from gemini"},
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                },
            },
        )

    client = _make_client(handler)
    resp = await client.chat([{"role": "user", "content": "hi"}])
    assert resp.message["content"] == "hello from gemini"
    assert resp.finish_reason == "stop"
    assert resp.usage.total_tokens == 15
    assert resp.usage.total_cost_usd == 0.0
    assert client.cumulative_cost == 0.0
    await client.aclose()


async def test_chat_raises_on_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="rate limited")

    client = _make_client(handler)
    with pytest.raises(GeminiError, match="429"):
        await client.chat([{"role": "user", "content": "x"}])
    await client.aclose()


async def test_chat_with_tool_calls() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode())
        assert "tools" in payload
        return httpx.Response(
            200,
            json={
                "model": "gemini-2.0-flash",
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_abc123",
                                    "type": "function",
                                    "function": {
                                        "name": "list_files",
                                        "arguments": "{}",
                                    },
                                }
                            ],
                        },
                    }
                ],
                "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
            },
        )

    client = _make_client(handler)
    resp = await client.chat(
        [{"role": "user", "content": "list my files"}],
        tools=[{
            "type": "function",
            "function": {
                "name": "list_files",
                "description": "list files",
                "parameters": {"type": "object", "properties": {}},
            },
        }],
    )
    assert resp.finish_reason == "tool_calls"
    tc = resp.message["tool_calls"][0]
    assert tc["function"]["name"] == "list_files"
    await client.aclose()


def test_requires_api_key() -> None:
    with pytest.raises(ValueError, match="API key"):
        GeminiClient(api_key="")
