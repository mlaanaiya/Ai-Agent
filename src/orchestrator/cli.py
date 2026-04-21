"""CLI entry point for the orchestrator.

    $ ai-agent ask "Summarize the Q3 meeting notes in folder Stratégie"
    $ ai-agent chat        # interactive REPL
    $ ai-agent tools       # list MCP tools discovered from the gateway
"""

from __future__ import annotations

import asyncio
import logging

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .agent import Agent
from .config import OrchestratorSettings
from .llm import build_llm
from .mcp_client import build_gateway

app = typer.Typer(
    add_completion=False,
    help=(
        "Minimal standalone agent runner (fallback when OpenClaw is not "
        "installed). For the reference deployment, use the `openclaw` CLI "
        "with the Drive gateway registered via scripts/register-openclaw.sh."
    ),
)
console = Console()


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


@app.command()
def ask(
    prompt: str = typer.Argument(..., help="User request."),
    model: str | None = typer.Option(None, help="Override LLM model."),
) -> None:
    """Run a single request and print the final answer."""
    settings = OrchestratorSettings()
    settings.ensure_valid()
    _setup_logging(settings.log_level)
    asyncio.run(_ask(settings, prompt, model))


async def _ask(settings: OrchestratorSettings, prompt: str, model: str | None) -> None:
    async with build_llm(settings) as llm:
        async with await build_gateway(settings) as mcp:
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
                f"[dim]steps={len(result.steps)} "
                f"stopped={result.stopped_reason}[/dim]"
            )


@app.command()
def chat(model: str | None = typer.Option(None, help="Override LLM model.")) -> None:
    """Interactive REPL (memory persists within the session)."""
    settings = OrchestratorSettings()
    settings.ensure_valid()
    _setup_logging(settings.log_level)
    asyncio.run(_chat(settings, model))


async def _chat(settings: OrchestratorSettings, model: str | None) -> None:
    async with build_llm(settings) as llm:
        async with await build_gateway(settings) as mcp:
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
                console.print(f"[dim]steps={len(result.steps)}[/dim]")


@app.command()
def tools() -> None:
    """List MCP tools exposed by the configured gateway."""
    settings = OrchestratorSettings()
    _setup_logging(settings.log_level)
    asyncio.run(_tools(settings))


async def _tools(settings: OrchestratorSettings) -> None:
    async with await build_gateway(settings) as mcp:
        table = Table(title="MCP tools")
        table.add_column("name", style="bold")
        table.add_column("description")
        for t in mcp.tools:
            table.add_row(t.name, t.description)
        console.print(table)


if __name__ == "__main__":
    app()
