"""Orchestrator configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class OrchestratorSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # OpenRouter
    openrouter_api_key: str = Field(default="", alias="OPENROUTER_API_KEY")
    openrouter_base_url: str = Field(
        default="https://openrouter.ai/api/v1", alias="OPENROUTER_BASE_URL"
    )
    openrouter_default_model: str = Field(
        default="anthropic/claude-3.5-sonnet", alias="OPENROUTER_DEFAULT_MODEL"
    )
    openrouter_max_cost_usd: float = Field(default=1.0, alias="OPENROUTER_MAX_COST_USD")
    openrouter_app_url: str = Field(default="", alias="OPENROUTER_APP_URL")
    openrouter_app_name: str = Field(default="ai-agent", alias="OPENROUTER_APP_NAME")

    # MCP transport
    mcp_transport: Literal["stdio", "http"] = Field(default="stdio", alias="MCP_TRANSPORT")
    mcp_server_url: str = Field(default="", alias="MCP_SERVER_URL")
    mcp_server_token: str = Field(default="", alias="MCP_SERVER_TOKEN")

    # Agent loop
    system_prompt_file: Path = Field(
        default=Path("./src/orchestrator/prompts/system.md"),
        alias="AGENT_SYSTEM_PROMPT_FILE",
    )
    max_steps: int = Field(default=8, alias="AGENT_MAX_STEPS")
    log_level: str = Field(default="INFO", alias="AGENT_LOG_LEVEL")

    def ensure_valid(self) -> None:
        if not self.openrouter_api_key:
            raise RuntimeError("OPENROUTER_API_KEY must be set.")
        if self.mcp_transport == "http" and not self.mcp_server_url:
            raise RuntimeError("MCP_SERVER_URL is required when MCP_TRANSPORT=http.")
        if self.max_steps <= 0:
            raise RuntimeError("AGENT_MAX_STEPS must be > 0.")

    def load_system_prompt(self) -> str:
        if self.system_prompt_file.exists():
            return self.system_prompt_file.read_text(encoding="utf-8")
        return DEFAULT_SYSTEM_PROMPT


DEFAULT_SYSTEM_PROMPT = """\
You are an autonomous assistant with access to a sandboxed Google Drive via MCP tools.

Guidelines:
  * Think step by step. Use tools only when they are genuinely useful.
  * Before reading a file, use list_files or search_drive to locate it.
  * Summaries must stay faithful to the source. Cite file names when relevant.
  * Never fabricate file IDs. If a file cannot be found, say so.
  * When the user asks for a deliverable, consider whether to persist it via save_file.
"""
