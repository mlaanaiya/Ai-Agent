"""CLI entry point for the orchestrator.

    $ ai-agent ask "Summarize the Q3 meeting notes in folder Stratégie"
    $ ai-agent chat        # interactive REPL
    $ ai-agent tools       # list MCP tools discovered from the gateway
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .agent import Agent
from .config import OrchestratorSettings
from .mcp_client import MCPGateway
from .openrouter import OpenRouterClient

app = typer.Typer(add_completion=False, help="OpenClaw-style AI agent CLI.")
console = Console()


async def _build_gateway(settings: OrchestratorSettings) -> MCPGateway:
    if settings.mcp_transport == "http":
        return await MCPGateway.connect_http(
            settings.mcp_server_url, token=settings.mcp_server_token or None
        )
    return await MCPGateway.connect_stdio()


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


@app.command()
def ask(
    prompt: str = typer.Argument(..., help="User request."),
    model: Optional[str] = typer.Option(None, help="Override OpenRouter model."),
) -> None:
    """Run a single request and print the final answer."""
    settings = OrchestratorSettings()
    settings.ensure_valid()
    _setup_logging(settings.log_level)
    asyncio.run(_ask(settings, prompt, model))


async def _ask(settings: OrchestratorSettings, prompt: str, model: str | None) -> None:
    async with OpenRouterClient(
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
        default_model=settings.openrouter_default_model,
        app_url=settings.openrouter_app_url,
        app_name=settings.openrouter_app_name,
        max_cost_usd=settings.openrouter_max_cost_usd,
    ) as llm:
        async with await _build_gateway(settings) as mcp:
            agent = Agent(
                llm=llm,
                mcp=mcp,
                system_prompt=settings.load_system_prompt(),
                model=model,
                max_steps=settings.max_steps,
            )
            result = await agent.run(prompt)
            console.print(Panel(result.final_text or "(empty)", title="Answer"))
            console.print(
                f"[dim]steps={len(result.steps)} cost=${result.total_cost_usd:.4f} "
                f"stopped={result.stopped_reason}[/dim]"
            )


@app.command()
def chat(model: Optional[str] = typer.Option(None, help="Override OpenRouter model.")) -> None:
    """Interactive REPL (memory persists within the session)."""
    settings = OrchestratorSettings()
    settings.ensure_valid()
    _setup_logging(settings.log_level)
    asyncio.run(_chat(settings, model))


async def _chat(settings: OrchestratorSettings, model: str | None) -> None:
    async with OpenRouterClient(
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
        default_model=settings.openrouter_default_model,
        app_url=settings.openrouter_app_url,
        app_name=settings.openrouter_app_name,
        max_cost_usd=settings.openrouter_max_cost_usd,
    ) as llm:
        async with await _build_gateway(settings) as mcp:
            agent = Agent(
                llm=llm,
                mcp=mcp,
                system_prompt=settings.load_system_prompt(),
                model=model,
                max_steps=settings.max_steps,
            )
            console.print("[bold]ai-agent chat[/bold] — Ctrl-D or /exit to quit.")
            while True:
                try:
                    prompt = console.input("[bold cyan]you>[/bold cyan] ").strip()
                except (EOFError, KeyboardInterrupt):
                    console.print()
                    break
                if not prompt:
                    continue
                if prompt in {"/exit", "/quit"}:
                    break
                if prompt == "/reset":
                    agent.memory.clear()
                    console.print("[dim]memory cleared[/dim]")
                    continue
                result = await agent.run(prompt)
                console.print(Panel(result.final_text or "(empty)", title="agent"))
                console.print(
                    f"[dim]cost=${result.total_cost_usd:.4f} "
                    f"(session total ${llm.cumulative_cost:.4f})[/dim]"
                )


@app.command()
def tools() -> None:
    """List MCP tools exposed by the configured gateway."""
    settings = OrchestratorSettings()
    _setup_logging(settings.log_level)
    asyncio.run(_tools(settings))


async def _tools(settings: OrchestratorSettings) -> None:
    async with await _build_gateway(settings) as mcp:
        table = Table(title="MCP tools")
        table.add_column("name", style="bold")
        table.add_column("description")
        for t in mcp.tools:
            table.add_row(t.name, t.description)
        console.print(table)


if __name__ == "__main__":
    app()
