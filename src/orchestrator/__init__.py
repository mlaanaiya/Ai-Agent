"""Minimal standalone agent runner (fallback when OpenClaw is not used).

The reference deployment described in the design note uses the real OpenClaw
(https://openclaw.ai) as the orchestrator — see `config/openclaw.config.json5`
and `scripts/register-openclaw.sh`.

This package is a small, self-contained alternative for cases where OpenClaw
is not available: CI, headless tests, air-gapped demos, or early prototyping.
It implements a minimal ReAct-style loop against OpenRouter and any MCP
server, so the Drive gateway can be exercised end-to-end without pulling in
the full OpenClaw runtime.
"""

__all__ = ["config", "gemini", "ollama", "llm", "mcp_client", "agent", "memory", "cli"]
