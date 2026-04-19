"""Tests for the Life Assistant DriveClient methods:
append_to_file, find_file_by_name, list_recent_files, overwrite_file."""

from __future__ import annotations

import io
from types import SimpleNamespace
from typing import Any

import pytest

from mcp_drive_server.drive import DriveClient, DriveError


def _make_client(fake_svc: Any, *, root: str = "root", max_bytes: int = 2_000_000):
    client = DriveClient.__new__(DriveClient)
    client._svc = fake_svc
    client._root = root
    client._allowed_mime = set()
    client._max_bytes = max_bytes
    return client


class FakeFiles:
    """Fake Drive files() endpoint that tracks downloads + uploads."""

    def __init__(self, metadata: dict[str, dict[str, Any]],
                 content: dict[str, bytes] | None = None):
        self._metadata = metadata
        self._content = content or {}
        self.updated: list[dict[str, Any]] = []
        self.uploaded_content: list[bytes] = []
        self.list_queries: list[str] = []
        self.list_results: dict[str, list[dict[str, Any]]] = {}

    def get(self, *, fileId, fields, supportsAllDrives=True):
        return SimpleNamespace(execute=lambda: self._metadata.get(fileId, {}))

    def get_media(self, *, fileId, supportsAllDrives=True):
        # Return a "request" object that the code will hand to MediaIoBaseDownload.
        return SimpleNamespace(
            _file_id=fileId,
            _content=self._content.get(fileId, b""),
        )

    def update(self, *, fileId, fields, supportsAllDrives=True, media_body=None,
               body=None, addParents=None, removeParents=None):
        record: dict[str, Any] = {"fileId": fileId}
        if media_body is not None:
            # Capture the upload content.
            stream = media_body._fd  # noqa: SLF001 — MediaIoBaseUpload attr
            stream.seek(0)
            self.uploaded_content.append(stream.read())
            record["uploaded"] = True
        if body:
            record["body"] = body
        self.updated.append(record)
        meta = dict(self._metadata.get(fileId, {}))
        meta["id"] = fileId
        return SimpleNamespace(execute=lambda: meta)

    def list(self, *, q, pageSize, fields, supportsAllDrives=True,
             includeItemsFromAllDrives=True, orderBy=None):
        self.list_queries.append(q)
        key = next((k for k in self.list_results if k in q), None)
        results = self.list_results.get(key or "", [])
        return SimpleNamespace(execute=lambda: {"files": results[:pageSize]})


class FakeDownloader:
    """Drop-in for MediaIoBaseDownload that consumes request._content."""

    def __init__(self, fd, request, chunksize=None):
        self._fd = fd
        self._request = request
        self._done = False

    def next_chunk(self):
        if self._done:
            return None, True
        self._fd.write(self._request._content)
        self._done = True
        return None, True


@pytest.fixture(autouse=True)
def _patch_download(monkeypatch):
    from mcp_drive_server import drive as drive_mod

    monkeypatch.setattr(drive_mod, "MediaIoBaseDownload", FakeDownloader)


# ---- find_file_by_name ----------------------------------------------------


def test_find_file_by_name_returns_hit():
    files = FakeFiles({"root": {"id": "root", "parents": []}})
    files.list_results["name = 'meds-log.jsonl'"] = [{
        "id": "log-1", "name": "meds-log.jsonl", "mimeType": "application/jsonl",
        "parents": ["root"],
    }]
    client = _make_client(SimpleNamespace(files=lambda: files))
    hit = client.find_file_by_name("meds-log.jsonl")
    assert hit is not None
    assert hit["id"] == "log-1"


def test_find_file_by_name_returns_none_when_missing():
    files = FakeFiles({"root": {"id": "root", "parents": []}})
    client = _make_client(SimpleNamespace(files=lambda: files))
    assert client.find_file_by_name("nope.txt") is None


# ---- append_to_file -------------------------------------------------------


def test_append_to_file_appends_with_newline_separator():
    existing = b'{"a":1}\n'
    files = FakeFiles(
        metadata={
            "log-1": {
                "id": "log-1", "name": "meds-log.jsonl",
                "mimeType": "application/jsonl", "parents": ["root"],
            },
            "root": {"id": "root", "parents": []},
        },
        content={"log-1": existing},
    )
    client = _make_client(SimpleNamespace(files=lambda: files))
    client.append_to_file("log-1", '{"b":2}')
    payload = files.uploaded_content[0].decode()
    assert payload == '{"a":1}\n{"b":2}'


def test_append_to_file_rejects_native_google_mime():
    files = FakeFiles({
        "sheet": {
            "id": "sheet", "name": "budget",
            "mimeType": "application/vnd.google-apps.spreadsheet",
            "parents": ["root"],
        },
        "root": {"id": "root", "parents": []},
    })
    client = _make_client(SimpleNamespace(files=lambda: files))
    with pytest.raises(DriveError, match="native Google type"):
        client.append_to_file("sheet", "x")


def test_append_to_file_respects_byte_cap():
    existing = b"x" * 500
    files = FakeFiles(
        metadata={
            "log-1": {
                "id": "log-1", "name": "log.txt",
                "mimeType": "text/plain", "parents": ["root"],
            },
            "root": {"id": "root", "parents": []},
        },
        content={"log-1": existing},
    )
    client = _make_client(SimpleNamespace(files=lambda: files), max_bytes=600)
    with pytest.raises(DriveError, match="exceed max_read_bytes"):
        client.append_to_file("log-1", "y" * 200)


# ---- overwrite_file -------------------------------------------------------


def test_overwrite_file_replaces_content():
    files = FakeFiles({
        "snap": {"id": "snap", "name": "snap.json", "mimeType": "application/json",
                 "parents": ["root"]},
        "root": {"id": "root", "parents": []},
    })
    client = _make_client(SimpleNamespace(files=lambda: files))
    client.overwrite_file("snap", '{"new":true}')
    assert files.uploaded_content[0] == b'{"new":true}'


def test_overwrite_file_rejects_native_google_mime():
    files = FakeFiles({
        "doc": {"id": "doc", "name": "d",
                "mimeType": "application/vnd.google-apps.document",
                "parents": ["root"]},
        "root": {"id": "root", "parents": []},
    })
    client = _make_client(SimpleNamespace(files=lambda: files))
    with pytest.raises(DriveError, match="native Google type"):
        client.overwrite_file("doc", "hi")


# ---- list_recent_files ----------------------------------------------------


def test_list_recent_files_returns_ordered_results():
    files = FakeFiles({"root": {"id": "root", "parents": []}})
    # Our fake list() matches on substring of the query. Use a distinctive
    # marker that only this query contains.
    files.list_results["trashed = false"] = [
        {"id": "f1", "name": "brief.md", "mimeType": "text/markdown",
         "modifiedTime": "2026-04-19T10:00:00Z", "parents": ["root"]},
        {"id": "f2", "name": "lab.pdf", "mimeType": "application/pdf",
         "modifiedTime": "2026-04-19T09:00:00Z", "parents": ["root"]},
    ]
    # _collect_descendant_folders also lists folders; give an empty response
    # for that query so the tree is just [root].
    client = _make_client(SimpleNamespace(files=lambda: files))
    # Patch _collect_descendant_folders to avoid hitting more queries.
    client._collect_descendant_folders = lambda root, max_depth=3: [root]  # type: ignore[method-assign]
    out = client.list_recent_files(max_results=5)
    assert [f.id for f in out] == ["f1", "f2"]
