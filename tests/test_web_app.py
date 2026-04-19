"""Integration tests for the FastAPI web app.

The SessionStore is patched to use fake OpenRouter + MCP components so tests
are hermetic — no subprocess, no network, no credentials.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from orchestrator.agent import Agent, AgentStepTrace
from orchestrator.config import OrchestratorSettings
from orchestrator.memory import ConversationMemory
from web.app import create_app


@dataclass
class FakeLLM:
    cumulative_cost: float = 0.0

    async def chat(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover
        raise NotImplementedError  # not used; we monkeypatch stream_events

    async def aclose(self) -> None:
        return None


@dataclass
class FakeMCP:
    _tools: list[Any] = field(default_factory=list)

    @property
    def tools(self) -> list[Any]:
        return self._tools

    def openai_tools(self) -> list[dict[str, Any]]:
        return []

    async def call(self, name: str, arguments: dict[str, Any]) -> str:
        return f"fake:{name}"

    async def aclose(self) -> None:
        return None


class FakeAgent(Agent):
    """Agent subclass whose stream_events yields a scripted sequence."""

    async def stream_events(self, user_prompt: str) -> AsyncIterator[dict[str, Any]]:
        self._memory.add_user(user_prompt)
        yield {"type": "user", "text": user_prompt}
        yield {"type": "llm_start", "step": 1}
        yield {
            "type": "tool_call",
            "step": 1,
            "id": "c1",
            "name": "list_files",
            "arguments": {},
        }
        yield {
            "type": "tool_result",
            "step": 1,
            "id": "c1",
            "name": "list_files",
            "content": '[{"id":"f1","name":"Q3.txt"}]',
            "error": False,
        }
        trace = AgentStepTrace(
            step=1, model="fake/model", finish_reason="tool_calls",
            prompt_tokens=5, completion_tokens=3, cost_usd=0.0002,
        )
        yield {"type": "step", "trace": trace}
        yield {
            "type": "final",
            "text": "I found Q3.txt in the folder.",
            "stopped_reason": "completed",
            "total_cost_usd": 0.0002,
        }


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DRIVE_ROOT_FOLDER_ID", "test-folder")

    from web import session_store as ss_module

    async def fake_create(self, title: str | None = None):
        import uuid
        from datetime import datetime, timezone
        llm = FakeLLM()
        mcp = FakeMCP()
        agent = FakeAgent(llm=llm, mcp=mcp, system_prompt="sys", max_steps=4)  # type: ignore[arg-type]
        entry = ss_module.SessionEntry(
            id=uuid.uuid4().hex[:12],
            title=title or f"Session {len(self._sessions) + 1}",
            created_at=datetime.now(timezone.utc),
            llm=llm,  # type: ignore[arg-type]
            mcp=mcp,  # type: ignore[arg-type]
            agent=agent,
        )
        self._sessions[entry.id] = entry
        return entry

    monkeypatch.setattr(ss_module.SessionStore, "create", fake_create)

    settings = OrchestratorSettings()
    app = create_app(settings)
    return TestClient(app)


def test_index_page_renders(client: TestClient) -> None:
    res = client.get("/")
    assert res.status_code == 200
    assert "AI Agent" in res.text
    assert "application/json" not in res.headers["content-type"]


def test_config_endpoint(client: TestClient) -> None:
    res = client.get("/api/config")
    assert res.status_code == 200
    data = res.json()
    assert "llm_configured" in data
    assert "llm_backend" in data
    assert "default_model" in data
    assert "mcp_transport" in data


def test_create_and_list_sessions(client: TestClient) -> None:
    res = client.post("/api/sessions", json={"title": "Test"})
    assert res.status_code == 200
    sid = res.json()["id"]
    res = client.get("/api/sessions")
    assert any(s["id"] == sid for s in res.json())


def test_chat_stream_yields_expected_events(client: TestClient) -> None:
    res = client.post("/api/chat", json={"prompt": "list files"})
    assert res.status_code == 200
    assert "text/event-stream" in res.headers["content-type"]
    body = res.text
    assert "event: session" in body
    assert "event: user" in body
    assert "event: tool_call" in body
    assert "event: tool_result" in body
    assert "event: final" in body
    assert "I found Q3.txt" in body


def test_transcript_persists_events(client: TestClient) -> None:
    res = client.post("/api/chat", json={"prompt": "list files"})
    assert res.status_code == 200
    # Find the session id assigned by the server.
    sessions = client.get("/api/sessions").json()
    sid = sessions[0]["id"]
    t = client.get(f"/api/sessions/{sid}/transcript").json()
    types = [e.get("type") for e in t["transcript"]]
    assert "user" in types and "tool_call" in types and "final" in types
    assert t["total_cost_usd"] > 0


def test_delete_session(client: TestClient) -> None:
    sid = client.post("/api/sessions", json={}).json()["id"]
    res = client.delete(f"/api/sessions/{sid}")
    assert res.status_code == 200
    # Gone:
    assert client.get(f"/api/sessions/{sid}/transcript").status_code == 404


def test_audit_endpoint_handles_missing_file(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from web import app as app_module

    monkeypatch.setattr(app_module, "_audit_path", lambda: tmp_path / "no.jsonl")
    res = client.get("/api/audit")
    assert res.status_code == 200
    assert res.json() == []


# ---- Quick-log endpoints ---------------------------------------------------


@pytest.fixture
def quicklog_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Same as `client` but also sets QUICKLOG_TOKEN."""
    monkeypatch.setenv("DRIVE_ROOT_FOLDER_ID", "test-folder")
    monkeypatch.setenv("QUICKLOG_TOKEN", "secret-token")

    from web import session_store as ss_module

    async def fake_create(self, title: str | None = None):
        import uuid
        from datetime import datetime, timezone
        llm = FakeLLM()
        mcp = FakeMCP()
        agent = FakeAgent(llm=llm, mcp=mcp, system_prompt="sys", max_steps=4)  # type: ignore[arg-type]
        entry = ss_module.SessionEntry(
            id=uuid.uuid4().hex[:12],
            title=title or f"Session {len(self._sessions) + 1}",
            created_at=datetime.now(timezone.utc),
            llm=llm,  # type: ignore[arg-type]
            mcp=mcp,  # type: ignore[arg-type]
            agent=agent,
        )
        self._sessions[entry.id] = entry
        return entry

    monkeypatch.setattr(ss_module.SessionStore, "create", fake_create)
    settings = OrchestratorSettings()
    app = create_app(settings)
    return TestClient(app)


def test_quicklog_requires_token(quicklog_client: TestClient) -> None:
    res = quicklog_client.post("/api/quicklog/med", json={"slot": "morning"})
    assert res.status_code == 401


def test_quicklog_med_accepts_valid_token(quicklog_client: TestClient) -> None:
    res = quicklog_client.post(
        "/api/quicklog/med",
        json={"slot": "morning", "note": "tacrolimus"},
        headers={"x-quicklog-token": "secret-token"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "completed"


def test_quicklog_vitals_validates_type(quicklog_client: TestClient) -> None:
    res = quicklog_client.post(
        "/api/quicklog/vitals",
        json={"type": "invalid", "value": 1},
        headers={"x-quicklog-token": "secret-token"},
    )
    assert res.status_code == 422


def test_quicklog_expense_requires_amount(quicklog_client: TestClient) -> None:
    res = quicklog_client.post(
        "/api/quicklog/expense",
        json={"merchant": "Carrefour"},
        headers={"x-quicklog-token": "secret-token"},
    )
    assert res.status_code == 422


def test_quicklog_expense_success(quicklog_client: TestClient) -> None:
    res = quicklog_client.post(
        "/api/quicklog/expense",
        json={"amount": 12.50, "merchant": "Carrefour", "category": "groceries"},
        headers={"x-quicklog-token": "secret-token"},
    )
    assert res.status_code == 200


def test_quicklog_todo_requires_text(quicklog_client: TestClient) -> None:
    res = quicklog_client.post(
        "/api/quicklog/todo",
        json={},
        headers={"x-quicklog-token": "secret-token"},
    )
    assert res.status_code == 422


def test_quicklog_reading_requires_url(quicklog_client: TestClient) -> None:
    res = quicklog_client.post(
        "/api/quicklog/reading",
        json={"title": "no url"},
        headers={"x-quicklog-token": "secret-token"},
    )
    assert res.status_code == 422


def test_quicklog_blocked_when_token_unset(client: TestClient) -> None:
    """When QUICKLOG_TOKEN is empty the endpoint returns 503, not 401."""
    res = client.post(
        "/api/quicklog/med",
        json={"slot": "morning"},
        headers={"x-quicklog-token": "anything"},
    )
    assert res.status_code == 503
