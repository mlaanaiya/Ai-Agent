"""Pydantic request/response models for the web API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    session_id: str | None = None
    model: str | None = None


class SessionSummary(BaseModel):
    id: str
    title: str
    created_at: str
    message_count: int
    total_cost_usd: float


class ToolInfo(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any]


class AuditEntry(BaseModel):
    ts: str
    tool: str
    status: str
    duration_ms: float
    arguments: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    result: dict[str, Any] | None = None


class ConfigStatus(BaseModel):
    openrouter_configured: bool
    drive_folder_configured: bool
    service_account_present: bool
    mcp_transport: str
    default_model: str
    max_cost_usd: float
    audit_log_path: str
    ready: bool
