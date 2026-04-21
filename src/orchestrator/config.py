"""Orchestrator configuration."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class MCPServerDefinition(BaseModel):
    """One MCP server declaration for the fallback orchestrator."""

    name: str
    transport: Literal["stdio", "http"] = "stdio"
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str | None = None
    token: str | None = None

    @field_validator("args", mode="before")
    @classmethod
    def _coerce_args(cls, value: object) -> object:
        if value is None:
            return []
        return value

    @field_validator("env", mode="before")
    @classmethod
    def _coerce_env(cls, value: object) -> object:
        if value is None:
            return {}
        return value


class OrchestratorSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # LLM backend selection
    llm_backend: Literal["gemini", "ollama", "openai"] = Field(
        default="gemini", alias="LLM_BACKEND"
    )

    # Gemini (free tier — default)
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-2.0-flash", alias="GEMINI_MODEL")
    gemini_timeout: float = Field(default=120.0, alias="GEMINI_TIMEOUT")

    # Ollama (local fallback)
    ollama_base_url: str = Field(
        default="http://localhost:11434/v1", alias="OLLAMA_BASE_URL"
    )
    ollama_default_model: str = Field(
        default="qwen2.5:7b", alias="OLLAMA_DEFAULT_MODEL"
    )
    ollama_timeout: float = Field(default=180.0, alias="OLLAMA_TIMEOUT")

    # OpenAI-compatible APIs (OpenAI, proxy, or compatible gateway)
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_base_url: str = Field(default="https://api.openai.com/v1", alias="OPENAI_BASE_URL")
    openai_model: str = Field(default="gpt-4.1-mini", alias="OPENAI_MODEL")
    openai_timeout: float = Field(default=120.0, alias="OPENAI_TIMEOUT")

    # MCP transport
    mcp_transport: Literal["stdio", "http"] = Field(default="stdio", alias="MCP_TRANSPORT")
    mcp_server_url: str = Field(default="", alias="MCP_SERVER_URL")
    mcp_server_token: str = Field(default="", alias="MCP_SERVER_TOKEN")
    mcp_servers_config_file: Path | None = Field(default=None, alias="MCP_SERVERS_CONFIG_FILE")

    # Telegram channel
    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    telegram_webhook_secret: str = Field(default="", alias="TELEGRAM_WEBHOOK_SECRET")
    telegram_allowed_user_ids: list[int] = Field(
        default_factory=list,
        alias="TELEGRAM_ALLOWED_USER_IDS",
    )
    telegram_allowed_chat_ids: list[int] = Field(
        default_factory=list,
        alias="TELEGRAM_ALLOWED_CHAT_IDS",
    )
    telegram_require_private_chat: bool = Field(
        default=True,
        alias="TELEGRAM_REQUIRE_PRIVATE_CHAT",
    )

    # Agent loop
    system_prompt_file: Path = Field(
        default=Path("./src/orchestrator/prompts/system.md"),
        alias="AGENT_SYSTEM_PROMPT_FILE",
    )
    max_steps: int = Field(default=8, alias="AGENT_MAX_STEPS")
    log_level: str = Field(default="INFO", alias="AGENT_LOG_LEVEL")

    @property
    def active_model_name(self) -> str:
        if self.llm_backend == "gemini":
            return self.gemini_model
        if self.llm_backend == "openai":
            return self.openai_model
        return self.ollama_default_model

    def ensure_valid(self) -> None:
        if self.llm_backend == "gemini" and not self.gemini_api_key:
            raise RuntimeError(
                "GEMINI_API_KEY must be set when LLM_BACKEND=gemini. "
                "Get a free key at https://aistudio.google.com/apikey"
            )
        if self.llm_backend == "openai" and not self.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY must be set when LLM_BACKEND=openai.")
        if self.mcp_servers_config_file and not self.mcp_servers_config_file.exists():
            raise RuntimeError(
                f"MCP_SERVERS_CONFIG_FILE does not exist: {self.mcp_servers_config_file}"
            )
        if self.mcp_servers_config_file:
            configs = self.load_mcp_servers()
            if not configs:
                raise RuntimeError(
                    "MCP_SERVERS_CONFIG_FILE is set but does not define any servers."
                )
            for server in configs:
                if server.transport == "http" and not server.url:
                    raise RuntimeError(
                        f"MCP server '{server.name}' uses HTTP transport but has no url."
                    )
                if server.transport == "stdio" and not server.command:
                    raise RuntimeError(
                        f"MCP server '{server.name}' uses stdio transport but has no command."
                    )
            if self.max_steps <= 0:
                raise RuntimeError("AGENT_MAX_STEPS must be > 0.")
            return
        if self.mcp_transport == "http" and not self.mcp_server_url:
            raise RuntimeError("MCP_SERVER_URL is required when MCP_TRANSPORT=http.")
        if self.max_steps <= 0:
            raise RuntimeError("AGENT_MAX_STEPS must be > 0.")

    def load_system_prompt(self) -> str:
        if self.system_prompt_file.exists():
            return self.system_prompt_file.read_text(encoding="utf-8")
        return DEFAULT_SYSTEM_PROMPT

    def load_mcp_servers(self) -> list[MCPServerDefinition]:
        if not self.mcp_servers_config_file:
            return []
        raw = json.loads(self.mcp_servers_config_file.read_text(encoding="utf-8"))
        items = raw if isinstance(raw, list) else raw.get("servers", [])
        return [
            MCPServerDefinition.model_validate(_expand_env_placeholders(item))
            for item in items
        ]

    @field_validator("telegram_allowed_user_ids", "telegram_allowed_chat_ids", mode="before")
    @classmethod
    def _split_int_csv(cls, value: object) -> object:
        if isinstance(value, str):
            parts = [item.strip() for item in value.split(",") if item.strip()]
            return [int(item) for item in parts]
        return value


DEFAULT_SYSTEM_PROMPT = """\
You are an autonomous assistant with access to a sandboxed Google Drive via MCP tools.

Guidelines:
  * Think step by step. Use tools only when they are genuinely useful.
  * Before reading a file, use list_files or search_drive to locate it.
  * Summaries must stay faithful to the source. Cite file names when relevant.
  * Never fabricate file IDs. If a file cannot be found, say so.
  * When the user asks for a deliverable, consider whether to persist it via save_file.
"""


def _expand_env_placeholders(value: Any) -> Any:
    """Expand ${VAR} placeholders inside JSON config values."""
    if isinstance(value, str):
        out = value
        for key, env_value in os.environ.items():
            out = out.replace(f"${{{key}}}", env_value)
        return out
    if isinstance(value, list):
        return [_expand_env_placeholders(item) for item in value]
    if isinstance(value, dict):
        return {key: _expand_env_placeholders(item) for key, item in value.items()}
    return value
