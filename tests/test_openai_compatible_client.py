"""Tests for the OpenAI-compatible client with a mocked HTTP transport."""

from __future__ import annotations

import json

import httpx
import pytest

from orchestrator.openai_compatible import OpenAICompatibleClient, OpenAICompatibleError


def _make_client(handler) -> OpenAICompatibleClient:
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(
        base_url="https://api.openai.com/v1",
        headers={
            "Authorization": "Bearer test-key",
            "Content-Type": "application/json",
        },
        transport=transport,
    )
    return OpenAICompatibleClient(
        api_key="test-key",
        default_model="gpt-4.1-mini",
        http_client=http,
    )


async def test_chat_parses_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode())
        assert payload["model"] == "gpt-4.1-mini"
        return httpx.Response(
            200,
            json={
                "model": "gpt-4.1-mini",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "hello from remote llm"},
                    }
                ],
                "usage": {
                    "prompt_tokens": 11,
                    "completion_tokens": 7,
                    "total_tokens": 18,
                },
            },
        )

    client = _make_client(handler)
    response = await client.chat([{"role": "user", "content": "hi"}])
    assert response.message["content"] == "hello from remote llm"
    assert response.finish_reason == "stop"
    assert response.usage.total_tokens == 18
    await client.aclose()


async def test_chat_with_tools() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode())
        assert "tools" in payload
        return httpx.Response(
            200,
            json={
                "model": "gpt-4.1-mini",
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
            },
        )

    client = _make_client(handler)
    response = await client.chat(
        [{"role": "user", "content": "list files"}],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "list_files",
                    "description": "list files",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
    )
    assert response.finish_reason == "tool_calls"
    assert response.message["tool_calls"][0]["function"]["name"] == "list_files"
    await client.aclose()


async def test_chat_raises_on_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="unauthorized")

    client = _make_client(handler)
    with pytest.raises(OpenAICompatibleError, match="401"):
        await client.chat([{"role": "user", "content": "x"}])
    await client.aclose()


def test_requires_api_key() -> None:
    with pytest.raises(ValueError, match="API key"):
        OpenAICompatibleClient(api_key="")
