"""Configuration for the enterprise MCP server."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class EnterpriseServerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    policies_dir: Path = Field(
        default=Path("./config/enterprise_policies"),
        alias="ENTERPRISE_POLICIES_DIR",
    )
    request_outbox: Path = Field(
        default=Path("./var/enterprise_requests"),
        alias="ENTERPRISE_REQUEST_OUTBOX",
    )
    audit_log: Path = Field(
        default=Path("./audit/mcp-enterprise.jsonl"),
        alias="ENTERPRISE_AUDIT_LOG",
    )
    max_policy_bytes: int = Field(
        default=250_000,
        alias="ENTERPRISE_MAX_POLICY_BYTES",
    )
    allowed_request_types: list[str] = Field(
        default_factory=lambda: ["access", "incident", "change"],
        alias="ENTERPRISE_ALLOWED_REQUEST_TYPES",
    )

    @field_validator("allowed_request_types", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    def ensure_valid(self) -> None:
        if self.max_policy_bytes <= 0:
            raise RuntimeError("ENTERPRISE_MAX_POLICY_BYTES must be > 0.")
        if not self.allowed_request_types:
            raise RuntimeError("ENTERPRISE_ALLOWED_REQUEST_TYPES must not be empty.")
