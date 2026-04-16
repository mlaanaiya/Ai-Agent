"""FastAPI app wiring the web UI to the agent + MCP gateway."""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from dataclasses import is_dataclass, asdict
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from orchestrator.config import OrchestratorSettings

from .schemas import AuditEntry, ChatRequest, ConfigStatus, SessionSummary, ToolInfo
from .session_store import SessionStore

logger = logging.getLogger(__name__)

PACKAGE_DIR = Path(__file__).resolve().parent
STATIC_DIR = PACKAGE_DIR / "static"
TEMPLATES_DIR = PACKAGE_DIR / "templates"


def _default_json(obj: Any) -> Any:
    if is_dataclass(obj):
        return asdict(obj)
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    return str(obj)


def _event_payload(event: dict[str, Any]) -> dict[str, Any]:
    """Make any agent event JSON-serializable (dataclasses → dicts)."""
    return json.loads(json.dumps(event, default=_default_json))


def create_app(settings: OrchestratorSettings | None = None) -> FastAPI:
    settings = settings or OrchestratorSettings()
    store = SessionStore(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.store = store
        try:
            yield
        finally:
            await store.close_all()

    app = FastAPI(title="AI Agent — Web UI", lifespan=lifespan)
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> Any:
        return templates.TemplateResponse(
            request,
            "index.html",
            {"default_model": settings.openrouter_default_model},
        )

    @app.get("/api/config", response_model=ConfigStatus)
    async def get_config() -> ConfigStatus:
        sa_path = Path("./secrets/service_account.json")
        has_or_key = bool(settings.openrouter_api_key and settings.openrouter_api_key != "test-key")
        has_drive = False
        audit_path = "./audit/mcp-drive.jsonl"
        # Peek at the Drive server settings without requiring them to be valid.
        try:
            from mcp_drive_server.config import DriveServerSettings

            drive_settings = DriveServerSettings()
            has_drive = bool(drive_settings.root_folder_id)
            sa_path = drive_settings.service_account_file
            audit_path = str(drive_settings.audit_log)
        except Exception:  # noqa: BLE001
            pass
        sa_present = Path(sa_path).exists()
        return ConfigStatus(
            openrouter_configured=has_or_key,
            drive_folder_configured=has_drive,
            service_account_present=sa_present,
            mcp_transport=settings.mcp_transport,
            default_model=settings.openrouter_default_model,
            max_cost_usd=settings.openrouter_max_cost_usd,
            audit_log_path=str(audit_path),
            ready=has_or_key and (has_drive or settings.mcp_transport == "http"),
        )

    @app.get("/api/tools", response_model=list[ToolInfo])
    async def list_tools() -> list[ToolInfo]:
        sessions = store.list_sessions()
        if sessions:
            mcp = sessions[0].mcp
        else:
            entry = await store.create(title="__tools_probe__")
            mcp = entry.mcp
        return [
            ToolInfo(name=t.name, description=t.description, parameters=t.parameters)
            for t in mcp.tools
        ]

    @app.get("/api/sessions", response_model=list[SessionSummary])
    async def list_sessions() -> list[SessionSummary]:
        return [SessionSummary(**s.summary()) for s in store.list_sessions()]

    @app.post("/api/sessions", response_model=SessionSummary)
    async def create_session(payload: dict[str, Any] | None = None) -> SessionSummary:
        title = (payload or {}).get("title") if payload else None
        entry = await store.create(title=title)
        return SessionSummary(**entry.summary())

    @app.delete("/api/sessions/{session_id}")
    async def delete_session(session_id: str) -> dict[str, bool]:
        ok = await store.delete(session_id)
        if not ok:
            raise HTTPException(status_code=404, detail="session not found")
        return {"ok": True}

    @app.get("/api/sessions/{session_id}/transcript")
    async def get_transcript(session_id: str) -> dict[str, Any]:
        try:
            entry = await store.require(session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="session not found") from exc
        return {
            "id": entry.id,
            "title": entry.title,
            "total_cost_usd": round(entry.total_cost_usd, 6),
            "transcript": entry.transcript,
        }

    @app.post("/api/chat")
    async def chat(req: ChatRequest) -> StreamingResponse:
        session_id = req.session_id
        if session_id:
            entry = await store.get(session_id)
            if entry is None:
                raise HTTPException(status_code=404, detail="session not found")
        else:
            entry = await store.create()

        if req.model:
            entry.agent._model = req.model  # type: ignore[attr-defined]  # intentional override

        async def gen() -> AsyncIterator[bytes]:
            # Make sure a single session can't run two chats at once.
            async with entry.lock:
                yield _sse(
                    "session",
                    {"id": entry.id, "title": entry.title},
                )
                try:
                    async for event in entry.agent.stream_events(req.prompt):
                        payload = _event_payload(event)
                        entry.transcript.append(payload)
                        if event["type"] == "final":
                            entry.total_cost_usd += event.get("total_cost_usd") or 0.0
                            # Update title from first user prompt if still default.
                            if entry.title.startswith("Session ") and entry.transcript:
                                first_user = next(
                                    (m for m in entry.transcript if m.get("type") == "user"),
                                    None,
                                )
                                if first_user:
                                    entry.title = (first_user["text"] or entry.title)[:60]
                        yield _sse(event["type"], payload)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("chat failed")
                    yield _sse("error", {"message": f"{type(exc).__name__}: {exc}"})
                yield _sse("done", {"cost_usd": round(entry.total_cost_usd, 6)})

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    @app.get("/api/audit", response_model=list[AuditEntry])
    async def recent_audit(limit: int = 50) -> list[AuditEntry]:
        audit_path = _audit_path()
        if not audit_path.exists():
            return []
        try:
            raw_lines = audit_path.read_text(encoding="utf-8").splitlines()[-limit:]
        except OSError:
            return []
        out: list[AuditEntry] = []
        for line in raw_lines:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            try:
                out.append(AuditEntry(**data))
            except Exception:  # noqa: BLE001
                continue
        return out

    return app


def _audit_path() -> Path:
    try:
        from mcp_drive_server.config import DriveServerSettings

        return Path(DriveServerSettings().audit_log)
    except Exception:  # noqa: BLE001
        return Path("./audit/mcp-drive.jsonl")


def _sse(event: str, data: Any) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, default=_default_json)}\n\n".encode("utf-8")
