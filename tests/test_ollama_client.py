"""Tests for the Ollama client with a mocked HTTP transport."""

from __future__ import annotations

import json

import httpx
import pytest

from orchestrator.ollama import OllamaClient, OllamaError


def _make_client(handler) -> OllamaClient:
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(
        base_url="http://localhost:11434/v1",
        headers={"Content-Type": "application/json"},
        transport=transport,
    )
    return OllamaClient(
        base_url="http://localhost:11434/v1",
        default_model="qwen2.5:7b",
        http_client=http,
    )


async def test_chat_parses_response_and_usage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode())
        assert payload["model"] == "qwen2.5:7b"
        assert payload["messages"][0]["role"] == "user"
        return httpx.Response(
            200,
            json={
                "model": "qwen2.5:7b",
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
                },
            },
        )

    client = _make_client(handler)
    resp = await client.chat([{"role": "user", "content": "hi"}])
    assert resp.message["content"] == "hello"
    assert resp.finish_reason == "stop"
    assert resp.usage.total_tokens == 15
    assert resp.usage.total_cost_usd == 0.0
    assert client.cumulative_cost == 0.0
    await client.aclose()


async def test_chat_raises_on_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="kaboom")

    client = _make_client(handler)
    with pytest.raises(OllamaError, match="500"):
        await client.chat([{"role": "user", "content": "x"}])
    await client.aclose()


async def test_chat_with_tools() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode())
        assert "tools" in payload
        return httpx.Response(
            200,
            json={
                "model": "qwen2.5:7b",
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
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
    tools = [
        {
            "type": "function",
            "function": {
                "name": "list_files",
                "description": "list files",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]
    resp = await client.chat(
        [{"role": "user", "content": "list files"}],
        tools=tools,
    )
    assert resp.finish_reason == "tool_calls"
    assert resp.message["tool_calls"][0]["function"]["name"] == "list_files"
    await client.aclose()
