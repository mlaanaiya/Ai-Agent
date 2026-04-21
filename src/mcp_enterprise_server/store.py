"""Least-privilege enterprise tools exposed through MCP."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


class EnterpriseError(RuntimeError):
    """Raised when an enterprise tool request is rejected."""


_SAFE_SLUG = re.compile(r"^[a-zA-Z0-9._-]+$")
_ALLOWED_POLICY_EXTENSIONS = (".md", ".txt")
_ALLOWED_PRIORITIES = {"low", "normal", "high", "urgent"}


@dataclass(slots=True)
class EnterpriseTools:
    policies_dir: Path
    request_outbox: Path
    max_policy_bytes: int
    allowed_request_types: set[str]

    def __post_init__(self) -> None:
        self.policies_dir.mkdir(parents=True, exist_ok=True)
        self.request_outbox.mkdir(parents=True, exist_ok=True)
        self.policies_dir = self.policies_dir.resolve()
        self.request_outbox = self.request_outbox.resolve()

    def list_policies(self, query: str | None = None) -> list[dict[str, object]]:
        needle = (query or "").strip().lower()
        rows: list[dict[str, object]] = []
        for path in sorted(self.policies_dir.iterdir()):
            if not path.is_file() or path.suffix.lower() not in _ALLOWED_POLICY_EXTENSIONS:
                continue
            slug = path.stem
            title = _title_from_path(path)
            if needle and needle not in slug.lower() and needle not in title.lower():
                continue
            stat = path.stat()
            rows.append(
                {
                    "slug": slug,
                    "title": title,
                    "path": path.name,
                    "size": stat.st_size,
                    "updated_at": datetime.fromtimestamp(
                        stat.st_mtime, tz=UTC
                    ).isoformat(timespec="seconds"),
                }
            )
        return rows

    def read_policy(self, slug: str) -> dict[str, object]:
        path = self._policy_path(slug)
        raw = path.read_bytes()
        if len(raw) > self.max_policy_bytes:
            raise EnterpriseError(
                f"Policy '{slug}' exceeds ENTERPRISE_MAX_POLICY_BYTES ({self.max_policy_bytes})."
            )
        content = raw.decode("utf-8", errors="replace")
        return {
            "slug": path.stem,
            "title": _title_from_text(path, content),
            "path": path.name,
            "size": len(raw),
            "content": content,
        }

    def create_request(
        self,
        request_type: str,
        title: str,
        details: str,
        *,
        priority: str = "normal",
        requester: str | None = None,
    ) -> dict[str, object]:
        normalized_type = request_type.strip().lower()
        normalized_priority = priority.strip().lower()
        clean_title = title.strip()
        clean_details = details.strip()
        clean_requester = (requester or "").strip() or None

        if normalized_type not in self.allowed_request_types:
            raise EnterpriseError(
                f"request_type '{request_type}' is not allowed by policy."
            )
        if normalized_priority not in _ALLOWED_PRIORITIES:
            raise EnterpriseError(
                f"priority '{priority}' must be one of {sorted(_ALLOWED_PRIORITIES)}."
            )
        if not clean_title:
            raise EnterpriseError("title must not be empty.")
        if not clean_details:
            raise EnterpriseError("details must not be empty.")
        if len(clean_title) > 160:
            raise EnterpriseError("title must be <= 160 characters.")
        if len(clean_details) > 5000:
            raise EnterpriseError("details must be <= 5000 characters.")
        if clean_requester and len(clean_requester) > 120:
            raise EnterpriseError("requester must be <= 120 characters.")

        request_id = f"req-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}"
        created_at = datetime.now(UTC).isoformat(timespec="seconds")
        payload = {
            "id": request_id,
            "created_at": created_at,
            "request_type": normalized_type,
            "priority": normalized_priority,
            "title": clean_title,
            "details": clean_details,
            "requester": clean_requester,
            "status": "queued",
        }
        target = self.request_outbox / f"{request_id}.json"
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "id": request_id,
            "status": "queued",
            "request_type": normalized_type,
            "priority": normalized_priority,
            "title": clean_title,
            "created_at": created_at,
        }

    def list_requests(self, limit: int = 20) -> list[dict[str, object]]:
        if limit <= 0:
            raise EnterpriseError("limit must be > 0.")
        rows: list[dict[str, object]] = []
        files = sorted(
            (path for path in self.request_outbox.iterdir() if path.is_file() and path.suffix == ".json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for path in files[: min(limit, 100)]:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise EnterpriseError(f"Queued request '{path.name}' is invalid JSON.") from exc
            rows.append(
                {
                    "id": payload.get("id"),
                    "created_at": payload.get("created_at"),
                    "request_type": payload.get("request_type"),
                    "priority": payload.get("priority"),
                    "title": payload.get("title"),
                    "status": payload.get("status", "queued"),
                }
            )
        return rows

    def _policy_path(self, slug: str) -> Path:
        candidate = slug.strip()
        if not candidate:
            raise EnterpriseError("slug must not be empty.")
        if not _SAFE_SLUG.fullmatch(candidate):
            raise EnterpriseError("slug contains forbidden characters.")

        direct = self.policies_dir / candidate
        candidates = [direct]
        if not direct.suffix:
            candidates.extend(self.policies_dir / f"{candidate}{suffix}" for suffix in _ALLOWED_POLICY_EXTENSIONS)

        for path in candidates:
            resolved = path.resolve()
            if resolved.parent != self.policies_dir:
                raise EnterpriseError("policy path escapes the approved directory.")
            if resolved.exists() and resolved.is_file() and resolved.suffix.lower() in _ALLOWED_POLICY_EXTENSIONS:
                return resolved
        raise EnterpriseError(f"Unknown policy '{slug}'.")


def _title_from_path(path: Path) -> str:
    return path.stem.replace("-", " ").replace("_", " ").strip().title()


def _title_from_text(path: Path, content: str) -> str:
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
        return stripped[:120]
    return _title_from_path(path)
