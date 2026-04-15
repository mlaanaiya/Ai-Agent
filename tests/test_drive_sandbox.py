"""Tests for DriveClient sandbox & policy enforcement.

We fake the Drive service object (`_svc`) to avoid any network or credential
dependency. Each test constructs a DriveClient via ``__new__`` and fills in the
attributes we care about, so we never call the real service-account loader.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from mcp_drive_server.drive import DriveClient, DriveError


def _make_client(
    fake_svc: Any,
    *,
    root: str = "root-folder",
    allowed: list[str] | None = None,
    max_bytes: int = 2_000_000,
) -> DriveClient:
    client = DriveClient.__new__(DriveClient)
    client._svc = fake_svc
    client._root = root
    client._allowed_mime = set(allowed or [])
    client._max_bytes = max_bytes
    return client


class FakeFilesEndpoint:
    """Minimal stand-in for drive.files() used by the sandbox checks."""

    def __init__(self, metadata: dict[str, dict[str, Any]]):
        self._metadata = metadata

    def get(self, *, fileId: str, fields: str, supportsAllDrives: bool):  # noqa: N803
        meta = self._metadata.get(fileId)
        if meta is None:
            raise KeyError(f"no such file {fileId}")
        return SimpleNamespace(execute=lambda: meta)


def test_descendant_of_root_direct_child() -> None:
    files = FakeFilesEndpoint(
        {
            "child": {"id": "child", "parents": ["root-folder"]},
        }
    )
    client = _make_client(SimpleNamespace(files=lambda: files))
    assert client._is_descendant_of_root("child") is True


def test_descendant_of_root_transitive() -> None:
    files = FakeFilesEndpoint(
        {
            "grandchild": {"id": "grandchild", "parents": ["child"]},
            "child": {"id": "child", "parents": ["root-folder"]},
        }
    )
    client = _make_client(SimpleNamespace(files=lambda: files))
    assert client._is_descendant_of_root("grandchild") is True


def test_file_outside_sandbox_is_rejected() -> None:
    files = FakeFilesEndpoint(
        {
            "stray": {"id": "stray", "parents": ["some-other-folder"]},
            "some-other-folder": {"id": "some-other-folder", "parents": []},
        }
    )
    client = _make_client(SimpleNamespace(files=lambda: files))
    with pytest.raises(DriveError, match="outside the sandbox"):
        client._assert_in_sandbox("stray")


def test_assert_mime_allowed_enforces_allow_list() -> None:
    client = _make_client(SimpleNamespace(), allowed=["text/plain"])
    client._assert_mime_allowed("text/plain")  # ok
    with pytest.raises(DriveError, match="not allowed"):
        client._assert_mime_allowed("application/zip")


def test_empty_allow_list_permits_any_mime() -> None:
    client = _make_client(SimpleNamespace(), allowed=[])
    # Must not raise.
    client._assert_mime_allowed("anything/at-all")


def test_save_file_rejects_path_traversal() -> None:
    files = FakeFilesEndpoint(
        {"root-folder": {"id": "root-folder", "parents": []}}
    )
    client = _make_client(SimpleNamespace(files=lambda: files))
    with pytest.raises(DriveError, match="must be non-empty"):
        client.save_file(name="", content="x")
    with pytest.raises(DriveError, match="must be non-empty"):
        client.save_file(name="foo/bar.txt", content="x")
