"""Tests for the new DriveClient methods: create_folder, get_metadata,
move_file, rename_file, delete_file — all with fake Drive service."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from mcp_drive_server.drive import DriveClient, DriveError


def _make_client(fake_svc: Any, *, root: str = "root-folder") -> DriveClient:
    client = DriveClient.__new__(DriveClient)
    client._svc = fake_svc
    client._root = root
    client._allowed_mime = set()
    client._max_bytes = 2_000_000
    return client


class FakeFiles:
    def __init__(self, metadata: dict[str, dict[str, Any]]):
        self._metadata = metadata
        self.created: list[dict[str, Any]] = []
        self.updated: list[dict[str, Any]] = []
        self.deleted: list[str] = []

    def get(self, *, fileId: str, fields: str, supportsAllDrives: bool = True):
        meta = self._metadata.get(fileId)
        if meta is None:
            raise KeyError(f"no such file {fileId}")
        return SimpleNamespace(execute=lambda: meta)

    def create(self, *, body: dict, fields: str, supportsAllDrives: bool = True,
               media_body: Any = None):
        self.created.append(body)
        result = {
            "id": "new-id",
            "name": body["name"],
            "mimeType": body.get("mimeType", "text/plain"),
            "parents": body.get("parents", []),
        }
        return SimpleNamespace(execute=lambda: result)

    def update(self, *, fileId: str, body: dict = None, addParents: str = None,
               removeParents: str = None, fields: str, supportsAllDrives: bool = True):
        self.updated.append({
            "fileId": fileId, "body": body,
            "addParents": addParents, "removeParents": removeParents,
        })
        meta = dict(self._metadata.get(fileId, {}))
        if body and "name" in body:
            meta["name"] = body["name"]
        if addParents:
            meta["parents"] = [addParents]
        return SimpleNamespace(execute=lambda: meta)

    def delete(self, *, fileId: str, supportsAllDrives: bool = True):
        self.deleted.append(fileId)
        return SimpleNamespace(execute=lambda: None)


def test_create_folder_in_sandbox() -> None:
    files = FakeFiles({
        "root-folder": {"id": "root-folder", "parents": []},
    })
    client = _make_client(SimpleNamespace(files=lambda: files))
    result = client.create_folder("Reports")
    assert result.name == "Reports"
    assert files.created[0]["mimeType"] == "application/vnd.google-apps.folder"


def test_create_folder_rejects_slash_in_name() -> None:
    client = _make_client(SimpleNamespace())
    with pytest.raises(DriveError, match="must be non-empty"):
        client.create_folder("a/b")


def test_get_metadata() -> None:
    files = FakeFiles({
        "f1": {
            "id": "f1", "name": "test.txt", "mimeType": "text/plain",
            "size": "100", "modifiedTime": "2026-01-01T00:00:00Z",
            "parents": ["root-folder"], "webViewLink": "https://...",
            "description": "test file",
        },
    })
    client = _make_client(SimpleNamespace(files=lambda: files))
    meta = client.get_metadata("f1")
    assert meta["name"] == "test.txt"
    assert meta["web_link"] == "https://..."
    assert meta["size"] == 100


def test_move_file() -> None:
    files = FakeFiles({
        "f1": {
            "id": "f1", "name": "test.txt", "mimeType": "text/plain",
            "parents": ["root-folder"],
        },
        "sub": {
            "id": "sub", "name": "subfolder", "mimeType": "application/vnd.google-apps.folder",
            "parents": ["root-folder"],
        },
    })
    client = _make_client(SimpleNamespace(files=lambda: files))
    result = client.move_file("f1", "sub")
    assert files.updated[0]["addParents"] == "sub"


def test_rename_file() -> None:
    files = FakeFiles({
        "f1": {
            "id": "f1", "name": "old.txt", "mimeType": "text/plain",
            "parents": ["root-folder"],
        },
    })
    client = _make_client(SimpleNamespace(files=lambda: files))
    result = client.rename_file("f1", "new.txt")
    assert result.name == "new.txt"


def test_rename_rejects_slash() -> None:
    client = _make_client(SimpleNamespace())
    with pytest.raises(DriveError, match="must be non-empty"):
        client.rename_file("f1", "a/b.txt")


def test_delete_file() -> None:
    files = FakeFiles({
        "f1": {
            "id": "f1", "name": "test.txt", "mimeType": "text/plain",
            "parents": ["root-folder"],
        },
    })
    client = _make_client(SimpleNamespace(files=lambda: files))
    result = client.delete_file("f1")
    assert result["status"] == "deleted"
    assert "f1" in files.deleted


def test_cannot_delete_root() -> None:
    files = FakeFiles({"root-folder": {"id": "root-folder", "parents": []}})
    client = _make_client(SimpleNamespace(files=lambda: files))
    with pytest.raises(DriveError, match="Cannot delete the sandbox root"):
        client.delete_file("root-folder")
