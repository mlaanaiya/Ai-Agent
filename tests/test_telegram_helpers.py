"""Unit tests for telegram_bot helper functions (no bot/network)."""

from telegram_bot import _split_text


def test_split_text_short() -> None:
    assert _split_text("hello", 100) == ["hello"]


def test_split_text_long() -> None:
    text = "line1\nline2\nline3\nline4\nline5"
    chunks = _split_text(text, 12)
    assert all(len(c) <= 12 for c in chunks)
    # All content is preserved (newlines between chunks are stripped by lstrip).
    joined = "\n".join(chunks)
    assert "line1" in joined and "line5" in joined


def test_split_text_no_newline() -> None:
    text = "a" * 200
    chunks = _split_text(text, 50)
    assert all(len(c) <= 50 for c in chunks)
    assert "".join(chunks) == text
