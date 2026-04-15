"""Sandboxed Google Drive wrapper.

Responsibilities:
  * Authenticate with a service account (OAuth credentials stay on this host).
  * Enforce that every operation targets a file inside DRIVE_ROOT_FOLDER_ID.
  * Enforce MIME-type allow-list and byte size limit on reads.
  * Expose a small, typed surface suitable for MCP tool bindings.

The service account model was chosen over user OAuth because the MCP server
runs headless. The target folder must be explicitly shared with the service
account's email address.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive"]

# MIME types that Drive exports as plain text/markdown for us.
GOOGLE_DOC_EXPORTS: dict[str, tuple[str, str]] = {
    "application/vnd.google-apps.document": ("text/plain", "txt"),
    "application/vnd.google-apps.spreadsheet": ("text/csv", "csv"),
    "application/vnd.google-apps.presentation": ("text/plain", "txt"),
}


class DriveError(RuntimeError):
    """Raised when a Drive operation is rejected or fails."""


@dataclass(slots=True)
class DriveFile:
    id: str
    name: str
    mime_type: str
    size: int | None
    modified_time: str | None
    parents: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "mime_type": self.mime_type,
            "size": self.size,
            "modified_time": self.modified_time,
            "parents": self.parents,
        }


class DriveClient:
    """Thin, safety-aware wrapper on top of the Google Drive v3 API."""

    def __init__(
        self,
        service_account_file: Path,
        root_folder_id: str,
        allowed_mime_types: list[str] | None = None,
        max_read_bytes: int = 2_000_000,
    ) -> None:
        if not root_folder_id:
            raise ValueError("root_folder_id is required")
        creds = service_account.Credentials.from_service_account_file(
            str(service_account_file), scopes=SCOPES
        )
        # cache_discovery=False avoids noisy warnings and a stale file cache.
        self._svc = build("drive", "v3", credentials=creds, cache_discovery=False)
        self._root = root_folder_id
        self._allowed_mime = set(allowed_mime_types or [])
        self._max_bytes = max_read_bytes

    # ---- Safety helpers ------------------------------------------------------

    def _is_descendant_of_root(self, file_id: str) -> bool:
        """Walk parents upward, bail out if we hit the root or exceed depth."""
        if file_id == self._root:
            return True
        visited: set[str] = set()
        current = file_id
        for _ in range(20):  # hard depth cap
            if current in visited:
                return False
            visited.add(current)
            try:
                meta = (
                    self._svc.files()
                    .get(fileId=current, fields="id,parents", supportsAllDrives=True)
                    .execute()
                )
            except HttpError as exc:
                raise DriveError(f"Drive metadata lookup failed for {current}: {exc}") from exc
            parents = meta.get("parents") or []
            if self._root in parents:
                return True
            if not parents:
                return False
            current = parents[0]
        return False

    def _assert_in_sandbox(self, file_id: str) -> None:
        if not self._is_descendant_of_root(file_id):
            raise DriveError(
                f"Access denied: file {file_id} is outside the sandbox folder."
            )

    def _assert_mime_allowed(self, mime_type: str) -> None:
        if self._allowed_mime and mime_type not in self._allowed_mime:
            raise DriveError(f"MIME type '{mime_type}' is not allowed by policy.")

    # ---- Tool implementations ------------------------------------------------

    def list_files(self, folder_id: str | None = None, query: str | None = None) -> list[DriveFile]:
        folder = folder_id or self._root
        self._assert_in_sandbox(folder)
        q_parts = [f"'{folder}' in parents", "trashed = false"]
        if query:
            # Escape single quotes for the Drive query language.
            safe = query.replace("'", "\\'")
            q_parts.append(f"name contains '{safe}'")
        q = " and ".join(q_parts)
        try:
            resp = (
                self._svc.files()
                .list(
                    q=q,
                    pageSize=100,
                    fields="files(id,name,mimeType,size,modifiedTime,parents)",
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                )
                .execute()
            )
        except HttpError as exc:
            raise DriveError(f"Drive list failed: {exc}") from exc
        return [_to_drive_file(f) for f in resp.get("files", [])]

    def search_drive(self, query: str, max_results: int = 20) -> list[DriveFile]:
        if not query.strip():
            raise DriveError("search_drive: query must not be empty.")
        safe = query.replace("'", "\\'")
        # Search is constrained to the sandbox via the 'in parents' recursion
        # trick: Drive does not support transitive 'in parents', so we first
        # enumerate descendant folders (one level of recursion, capped).
        descendant_folders = self._collect_descendant_folders(self._root, max_depth=3)
        parent_clause = " or ".join(f"'{fid}' in parents" for fid in descendant_folders)
        q = f"({parent_clause}) and name contains '{safe}' and trashed = false"
        try:
            resp = (
                self._svc.files()
                .list(
                    q=q,
                    pageSize=min(max_results, 100),
                    fields="files(id,name,mimeType,size,modifiedTime,parents)",
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                )
                .execute()
            )
        except HttpError as exc:
            raise DriveError(f"Drive search failed: {exc}") from exc
        return [_to_drive_file(f) for f in resp.get("files", [])]

    def _collect_descendant_folders(self, root: str, max_depth: int) -> list[str]:
        out = [root]
        frontier = [root]
        for _ in range(max_depth):
            next_frontier: list[str] = []
            for parent in frontier:
                try:
                    resp = (
                        self._svc.files()
                        .list(
                            q=(
                                f"'{parent}' in parents and "
                                "mimeType = 'application/vnd.google-apps.folder' and "
                                "trashed = false"
                            ),
                            pageSize=100,
                            fields="files(id)",
                            supportsAllDrives=True,
                            includeItemsFromAllDrives=True,
                        )
                        .execute()
                    )
                except HttpError:
                    continue
                for f in resp.get("files", []):
                    next_frontier.append(f["id"])
                    out.append(f["id"])
            if not next_frontier:
                break
            frontier = next_frontier
        return out

    def read_document(self, file_id: str) -> dict[str, Any]:
        self._assert_in_sandbox(file_id)
        try:
            meta = (
                self._svc.files()
                .get(
                    fileId=file_id,
                    fields="id,name,mimeType,size,modifiedTime,parents",
                    supportsAllDrives=True,
                )
                .execute()
            )
        except HttpError as exc:
            raise DriveError(f"Drive metadata lookup failed: {exc}") from exc

        mime = meta["mimeType"]
        self._assert_mime_allowed(mime)
        name = meta["name"]

        buf = io.BytesIO()
        try:
            if mime in GOOGLE_DOC_EXPORTS:
                export_mime, _ = GOOGLE_DOC_EXPORTS[mime]
                request = self._svc.files().export_media(fileId=file_id, mimeType=export_mime)
            else:
                request = self._svc.files().get_media(fileId=file_id, supportsAllDrives=True)
            downloader = MediaIoBaseDownload(buf, request, chunksize=256 * 1024)
            done = False
            while not done:
                _, done = downloader.next_chunk()
                if buf.tell() > self._max_bytes:
                    raise DriveError(
                        f"File exceeds max_read_bytes ({self._max_bytes}); truncate upstream."
                    )
        except HttpError as exc:
            raise DriveError(f"Drive download failed: {exc}") from exc

        raw = buf.getvalue()
        try:
            text = raw.decode("utf-8")
            encoding = "utf-8"
        except UnicodeDecodeError:
            text = raw.decode("latin-1", errors="replace")
            encoding = "latin-1"

        return {
            "id": meta["id"],
            "name": name,
            "mime_type": mime,
            "size": len(raw),
            "encoding": encoding,
            "content": text,
        }

    def save_file(
        self,
        name: str,
        content: str,
        folder_id: str | None = None,
        mime_type: str = "text/plain",
    ) -> DriveFile:
        if not name or "/" in name:
            raise DriveError("save_file: 'name' must be non-empty and contain no '/'.")
        parent = folder_id or self._root
        self._assert_in_sandbox(parent)
        body = {"name": name, "parents": [parent]}
        data = io.BytesIO(content.encode("utf-8"))
        media = MediaIoBaseUpload(data, mimetype=mime_type, resumable=False)
        try:
            created = (
                self._svc.files()
                .create(
                    body=body,
                    media_body=media,
                    fields="id,name,mimeType,size,modifiedTime,parents",
                    supportsAllDrives=True,
                )
                .execute()
            )
        except HttpError as exc:
            raise DriveError(f"Drive upload failed: {exc}") from exc
        return _to_drive_file(created)


def _to_drive_file(raw: dict[str, Any]) -> DriveFile:
    size_raw = raw.get("size")
    return DriveFile(
        id=raw["id"],
        name=raw["name"],
        mime_type=raw["mimeType"],
        size=int(size_raw) if size_raw is not None else None,
        modified_time=raw.get("modifiedTime"),
        parents=list(raw.get("parents", [])),
    )


@lru_cache(maxsize=1)
def _cached_client_cache_key() -> None:  # pragma: no cover - placeholder for future caching
    return None
