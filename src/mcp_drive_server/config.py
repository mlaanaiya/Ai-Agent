"""Configuration for the MCP Drive server.

All settings are loaded from environment variables (see .env.example). A
Pydantic model validates them eagerly so misconfiguration fails fast.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DriveServerSettings(BaseSettings):
    """Runtime configuration for the Drive MCP server."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    service_account_file: Path = Field(
        default=Path("./secrets/service_account.json"),
        alias="GOOGLE_SERVICE_ACCOUNT_FILE",
    )
    root_folder_id: str = Field(default="", alias="DRIVE_ROOT_FOLDER_ID")
    allowed_mime_types: list[str] = Field(
        default_factory=list,
        alias="DRIVE_ALLOWED_MIME_TYPES",
    )
    max_read_bytes: int = Field(default=2_000_000, alias="DRIVE_MAX_READ_BYTES")
    audit_log: Path = Field(
        default=Path("./audit/mcp-drive.jsonl"),
        alias="MCP_AUDIT_LOG",
    )

    @field_validator("allowed_mime_types", mode="before")
    @classmethod
    def _split_csv(cls, v: object) -> object:
        if isinstance(v, str):
            return [item.strip() for item in v.split(",") if item.strip()]
        return v

    def ensure_valid(self) -> None:
        """Raise if mandatory settings are missing or obviously wrong."""
        if not self.root_folder_id:
            raise RuntimeError(
                "DRIVE_ROOT_FOLDER_ID must be set — the agent only operates "
                "inside a single, explicitly-shared Drive folder."
            )
        if not self.service_account_file.exists():
            raise RuntimeError(
                f"Service account JSON not found: {self.service_account_file}. "
                "Create a Google service account, grant it Drive access on the "
                "target folder, and point GOOGLE_SERVICE_ACCOUNT_FILE to the key file."
            )
        if self.max_read_bytes <= 0:
            raise RuntimeError("DRIVE_MAX_READ_BYTES must be > 0.")
