"""Autonomous agent orchestrator (OpenClaw-style).

Daemon that receives user requests, picks the best LLM via OpenRouter,
invokes MCP tools (Drive gateway & others), and returns the answer.
"""

__all__ = ["config", "openrouter", "mcp_client", "agent", "memory", "cli"]
