"""In-memory session registry.

Each browser session maps to an Agent + a persistent MCPGateway connection.
The store is safe for concurrent FastAPI handlers thanks to per-session async
locks, but it deliberately keeps everything in-process — for multi-worker
deployments, swap the implementation for a Redis/SQLite-backed one.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from orchestrator.agent import Agent
from orchestrator.config import OrchestratorSettings
from orchestrator.mcp_client import MCPGateway
from orchestrator.ollama import OllamaClient


@dataclass(slots=True)
class SessionEntry:
    id: str
    title: str
    created_at: datetime
    llm: OllamaClient
    mcp: MCPGateway
    agent: Agent
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    transcript: list[dict[str, Any]] = field(default_factory=list)
    total_cost_usd: float = 0.0

    def summary(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at.isoformat(timespec="seconds"),
            "message_count": sum(1 for m in self.transcript if m["type"] in {"user", "final"}),
            "total_cost_usd": round(self.total_cost_usd, 6),
        }


class SessionStore:
    def __init__(self, settings: OrchestratorSettings) -> None:
        self._settings = settings
        self._sessions: dict[str, SessionEntry] = {}
        self._lock = asyncio.Lock()

    @property
    def settings(self) -> OrchestratorSettings:
        return self._settings

    async def create(self, title: str | None = None) -> SessionEntry:
        async with self._lock:
            sid = uuid.uuid4().hex[:12]
            llm = OllamaClient(
                base_url=self._settings.ollama_base_url,
                default_model=self._settings.ollama_default_model,
                timeout=self._settings.ollama_timeout,
            )
            mcp = await self._connect_mcp()
            agent = Agent(
                llm=llm,
                mcp=mcp,
                system_prompt=self._settings.load_system_prompt(),
                max_steps=self._settings.max_steps,
            )
            entry = SessionEntry(
                id=sid,
                title=title or f"Session {len(self._sessions) + 1}",
                created_at=datetime.now(timezone.utc),
                llm=llm,
                mcp=mcp,
                agent=agent,
            )
            self._sessions[sid] = entry
            return entry

    async def _connect_mcp(self) -> MCPGateway:
        if self._settings.mcp_transport == "http":
            return await MCPGateway.connect_http(
                self._settings.mcp_server_url,
                token=self._settings.mcp_server_token or None,
            )
        return await MCPGateway.connect_stdio()

    async def get(self, session_id: str) -> SessionEntry | None:
        return self._sessions.get(session_id)

    async def require(self, session_id: str) -> SessionEntry:
        entry = self._sessions.get(session_id)
        if entry is None:
            raise KeyError(session_id)
        return entry

    def list_sessions(self) -> list[SessionEntry]:
        return sorted(self._sessions.values(), key=lambda s: s.created_at, reverse=True)

    async def delete(self, session_id: str) -> bool:
        async with self._lock:
            entry = self._sessions.pop(session_id, None)
        if entry is None:
            return False
        await self._close(entry)
        return True

    async def close_all(self) -> None:
        async with self._lock:
            entries = list(self._sessions.values())
            self._sessions.clear()
        for entry in entries:
            await self._close(entry)

    @staticmethod
    async def _close(entry: SessionEntry) -> None:
        try:
            await entry.mcp.aclose()
        except Exception:  # noqa: BLE001
            pass
        try:
            await entry.llm.aclose()
        except Exception:  # noqa: BLE001
            pass
