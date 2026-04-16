"""Telegram bot that fronts the AI agent.

Each Telegram chat gets its own Agent instance (session) with persistent
memory for the conversation lifetime. The bot streams agent events back by
editing a single "working…" message as tool calls and results arrive, then
sends the final answer as a clean new message.

Usage:
    export TELEGRAM_BOT_TOKEN=<token from @BotFather>
    python -m telegram_bot
"""

from __future__ import annotations

import html
import json
import logging
import os
import sys
from typing import Any

from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from orchestrator.agent import Agent
from orchestrator.config import OrchestratorSettings
from orchestrator.mcp_client import MCPGateway
from orchestrator.openrouter import OpenRouterClient

logger = logging.getLogger(__name__)

# ── Session registry ────────────────────────────────────────────────────────

_sessions: dict[int, dict[str, Any]] = {}  # chat_id → {agent, llm, mcp}


async def _get_or_create_session(chat_id: int, settings: OrchestratorSettings) -> Agent:
    if chat_id in _sessions:
        return _sessions[chat_id]["agent"]

    llm = OpenRouterClient(
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
        default_model=settings.openrouter_default_model,
        app_url=settings.openrouter_app_url,
        app_name=settings.openrouter_app_name,
        max_cost_usd=settings.openrouter_max_cost_usd,
    )
    if settings.mcp_transport == "http":
        mcp = await MCPGateway.connect_http(
            settings.mcp_server_url, token=settings.mcp_server_token or None
        )
    else:
        mcp = await MCPGateway.connect_stdio()

    agent = Agent(
        llm=llm,
        mcp=mcp,
        system_prompt=settings.load_system_prompt(),
        max_steps=settings.max_steps,
    )
    _sessions[chat_id] = {"agent": agent, "llm": llm, "mcp": mcp}
    return agent


async def _close_session(chat_id: int) -> None:
    entry = _sessions.pop(chat_id, None)
    if entry is None:
        return
    try:
        await entry["mcp"].aclose()
    except Exception:  # noqa: BLE001
        pass
    try:
        await entry["llm"].aclose()
    except Exception:  # noqa: BLE001
        pass


# ── Handlers ────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Hi! I'm your Drive document assistant.\n\n"
        "Send me a message and I'll search, read, or summarise files "
        "from the configured sandbox folder.\n\n"
        "Commands:\n"
        "/reset — clear conversation memory\n"
        "/tools — list available MCP tools\n"
        "/cost  — show session cost so far\n"
        "/help  — this message",
    )


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    await _close_session(chat_id)
    await update.message.reply_text("Session cleared. Send a new message to start fresh.")


async def cmd_tools(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: OrchestratorSettings = context.bot_data["settings"]
    agent = await _get_or_create_session(update.effective_chat.id, settings)
    mcp = _sessions[update.effective_chat.id]["mcp"]
    lines = [f"<b>{html.escape(t.name)}</b>\n{html.escape(t.description)}" for t in mcp.tools]
    await update.message.reply_text(
        "\n\n".join(lines) or "No tools discovered.",
        parse_mode=ParseMode.HTML,
    )


async def cmd_cost(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    entry = _sessions.get(update.effective_chat.id)
    if entry:
        cost = entry["llm"].cumulative_cost
        await update.message.reply_text(f"Session cost: ${cost:.4f} USD")
    else:
        await update.message.reply_text("No active session.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_text = (update.message.text or "").strip()
    if not user_text:
        return

    settings: OrchestratorSettings = context.bot_data["settings"]
    chat_id = update.effective_chat.id
    agent = await _get_or_create_session(chat_id, settings)

    # Send a "working" message we'll edit as events stream in.
    await update.effective_chat.send_action(ChatAction.TYPING)
    status_msg = await update.message.reply_text("Thinking…")

    status_lines: list[str] = []
    final_text = ""

    try:
        async for event in agent.stream_events(user_text):
            etype = event["type"]

            if etype == "tool_call":
                name = event["name"]
                args_str = json.dumps(event.get("arguments", {}), ensure_ascii=False)
                if len(args_str) > 120:
                    args_str = args_str[:117] + "…"
                status_lines.append(f"🔧 <b>{html.escape(name)}</b>({html.escape(args_str)})")
                try:
                    await status_msg.edit_text(
                        "\n".join(status_lines) + "\n\n<i>running…</i>",
                        parse_mode=ParseMode.HTML,
                    )
                except Exception:  # noqa: BLE001 — rate-limit or no-change
                    pass

            elif etype == "tool_result":
                ok = "ok" if not event.get("error") else "error"
                status_lines[-1] += f"  → <i>{ok}</i>"
                try:
                    await status_msg.edit_text(
                        "\n".join(status_lines) + "\n\n<i>thinking…</i>",
                        parse_mode=ParseMode.HTML,
                    )
                except Exception:  # noqa: BLE001
                    pass

            elif etype == "final":
                final_text = event.get("text") or ""

    except Exception as exc:  # noqa: BLE001
        logger.exception("agent error for chat %s", chat_id)
        final_text = f"Error: {type(exc).__name__}: {exc}"

    # Clean up the status message and send the final answer.
    if status_lines:
        try:
            await status_msg.edit_text(
                "\n".join(status_lines), parse_mode=ParseMode.HTML
            )
        except Exception:  # noqa: BLE001
            pass
    else:
        try:
            await status_msg.delete()
        except Exception:  # noqa: BLE001
            pass

    if final_text:
        # Split long messages (Telegram 4096 char limit).
        for chunk in _split_text(final_text, 4000):
            await update.message.reply_text(chunk)


def _split_text(text: str, max_len: int) -> list[str]:
    if len(text) <= max_len:
        return [text]
    chunks: list[str] = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        # Try to split on newline near the boundary.
        idx = text.rfind("\n", 0, max_len)
        if idx < max_len // 2:
            idx = max_len
        chunks.append(text[:idx])
        text = text[idx:].lstrip("\n")
    return chunks


# ── Entry point ─────────────────────────────────────────────────────────────

def main() -> int:
    logging.basicConfig(
        level=os.environ.get("AGENT_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN is not set.")
        return 1

    settings = OrchestratorSettings()
    settings.ensure_valid()

    app = Application.builder().token(token).build()
    app.bot_data["settings"] = settings

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CommandHandler("tools", cmd_tools))
    app.add_handler(CommandHandler("cost", cmd_cost))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Starting Telegram bot (polling)…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
