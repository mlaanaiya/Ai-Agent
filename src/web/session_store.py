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
from datetime import UTC, datetime
from typing import Any

from orchestrator.agent import Agent
from orchestrator.config import OrchestratorSettings
from orchestrator.llm import build_llm
from orchestrator.mcp_client import build_gateway


@dataclass(slots=True)
class SessionEntry:
    id: str
    title: str
    created_at: datetime
    llm: Any
    mcp: Any
    agent: Agent
    external_key: str | None = None
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
        self._external_keys: dict[str, str] = {}
        self._lock = asyncio.Lock()

    @property
    def settings(self) -> OrchestratorSettings:
        return self._settings

    async def create(self, title: str | None = None) -> SessionEntry:
        async with self._lock:
            sid = uuid.uuid4().hex[:12]
            llm = build_llm(self._settings)
            mcp = await build_gateway(self._settings)
            agent = Agent(
                llm=llm,
                mcp=mcp,
                system_prompt=self._settings.load_system_prompt(),
                max_steps=self._settings.max_steps,
            )
            entry = SessionEntry(
                id=sid,
                title=title or f"Session {len(self._sessions) + 1}",
                created_at=datetime.now(UTC),
                llm=llm,
                mcp=mcp,
                agent=agent,
            )
            self._sessions[sid] = entry
            return entry

    async def get_or_create_by_key(
        self,
        external_key: str,
        *,
        title: str | None = None,
    ) -> SessionEntry:
        async with self._lock:
            session_id = self._external_keys.get(external_key)
            if session_id:
                entry = self._sessions.get(session_id)
                if entry is not None:
                    return entry

            sid = uuid.uuid4().hex[:12]
            llm = build_llm(self._settings)
            mcp = await build_gateway(self._settings)
            agent = Agent(
                llm=llm,
                mcp=mcp,
                system_prompt=self._settings.load_system_prompt(),
                max_steps=self._settings.max_steps,
            )
            entry = SessionEntry(
                id=sid,
                title=title or f"Session {len(self._sessions) + 1}",
                created_at=datetime.now(UTC),
                llm=llm,
                mcp=mcp,
                agent=agent,
                external_key=external_key,
            )
            self._sessions[sid] = entry
            self._external_keys[external_key] = sid
            return entry

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
            if entry and entry.external_key:
                self._external_keys.pop(entry.external_key, None)
        if entry is None:
            return False
        await self._close(entry)
        return True

    async def close_all(self) -> None:
        async with self._lock:
            entries = list(self._sessions.values())
            self._sessions.clear()
            self._external_keys.clear()
        for entry in entries:
            await self._close(entry)

    @staticmethod
    async def _close(entry: SessionEntry) -> None:
        try:
            await entry.mcp.aclose()
        except Exception:
            pass
        try:
            await entry.llm.aclose()
        except Exception:
            pass
