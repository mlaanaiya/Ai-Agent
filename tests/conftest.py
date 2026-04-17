"""Shared pytest fixtures."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure `src/` is importable without installing the package.
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# Default to ollama backend for tests (no API key needed).
os.environ.setdefault("LLM_BACKEND", "ollama")
