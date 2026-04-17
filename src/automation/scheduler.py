"""Cron-like scheduler for automated agent prompts.

Reads job definitions from a YAML/JSON config file (see automation.example.yml)
and runs them on schedule. Each run creates a fresh Agent session so memory
does not bleed across runs. Results are logged and optionally saved to Drive.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from orchestrator.agent import Agent, AgentResult
from orchestrator.config import OrchestratorSettings
from orchestrator.llm import build_llm
from orchestrator.mcp_client import MCPGateway

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class JobDefinition:
    """A single scheduled prompt."""
    name: str
    prompt: str
    cron: str  # simplified: "daily", "hourly", "weekly", or seconds interval
    model: str | None = None
    save_result: bool = False
    save_folder_id: str | None = None
    enabled: bool = True


@dataclass(slots=True)
class JobRun:
    job_name: str
    started_at: str
    finished_at: str
    status: str  # "ok" | "error"
    result_text: str
    cost_usd: float
    steps: int
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_name": self.job_name,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "status": self.status,
            "result_text": self.result_text[:500],
            "cost_usd": self.cost_usd,
            "steps": self.steps,
            "error": self.error,
        }


def _parse_interval_seconds(cron: str) -> int:
    cron = cron.strip().lower()
    if cron == "hourly":
        return 3600
    if cron == "daily":
        return 86400
    if cron == "weekly":
        return 604800
    if cron.endswith("m"):
        return int(cron[:-1]) * 60
    if cron.endswith("h"):
        return int(cron[:-1]) * 3600
    if cron.endswith("s"):
        return int(cron[:-1])
    return int(cron)


def load_jobs(path: Path) -> list[JobDefinition]:
    """Load job definitions from a JSON file."""
    if not path.exists():
        logger.warning("Jobs file not found: %s", path)
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    jobs_raw = raw if isinstance(raw, list) else raw.get("jobs", [])
    jobs: list[JobDefinition] = []
    for item in jobs_raw:
        jobs.append(
            JobDefinition(
                name=item["name"],
                prompt=item["prompt"],
                cron=item.get("cron", "daily"),
                model=item.get("model"),
                save_result=item.get("save_result", False),
                save_folder_id=item.get("save_folder_id"),
                enabled=item.get("enabled", True),
            )
        )
    return jobs


class Scheduler:
    """Simple interval-based scheduler that runs jobs in a loop."""

    def __init__(self, settings: OrchestratorSettings, jobs: list[JobDefinition]) -> None:
        self._settings = settings
        self._jobs = [j for j in jobs if j.enabled]
        self._history: list[JobRun] = []
        self._running = False

    @property
    def history(self) -> list[JobRun]:
        return list(self._history)

    async def run_once(self, job: JobDefinition) -> JobRun:
        """Execute a single job and return the run record."""
        started = datetime.now(timezone.utc).isoformat(timespec="seconds")
        llm = build_llm(self._settings)
        mcp: MCPGateway | None = None
        try:
            if self._settings.mcp_transport == "http":
                mcp = await MCPGateway.connect_http(
                    self._settings.mcp_server_url,
                    token=self._settings.mcp_server_token or None,
                )
            else:
                mcp = await MCPGateway.connect_stdio()

            agent = Agent(
                llm=llm,
                mcp=mcp,
                system_prompt=self._settings.load_system_prompt(),
                model=job.model,
                max_steps=self._settings.max_steps,
            )
            result = await agent.run(job.prompt)
            finished = datetime.now(timezone.utc).isoformat(timespec="seconds")

            # Optionally save the result to Drive.
            if job.save_result and result.final_text:
                ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
                fname = f"{job.name}-{ts}.txt"
                try:
                    await mcp.call(
                        "save_file",
                        {
                            "name": fname,
                            "content": result.final_text,
                            "folder_id": job.save_folder_id,
                        },
                    )
                    logger.info("Job '%s' result saved as %s", job.name, fname)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Job '%s': failed to save result: %s", job.name, exc)

            run = JobRun(
                job_name=job.name,
                started_at=started,
                finished_at=finished,
                status="ok",
                result_text=result.final_text,
                cost_usd=result.total_cost_usd,
                steps=len(result.steps),
            )
        except Exception as exc:  # noqa: BLE001
            finished = datetime.now(timezone.utc).isoformat(timespec="seconds")
            run = JobRun(
                job_name=job.name,
                started_at=started,
                finished_at=finished,
                status="error",
                result_text="",
                cost_usd=0.0,
                steps=0,
                error=f"{type(exc).__name__}: {exc}",
            )
            logger.exception("Job '%s' failed", job.name)
        finally:
            if mcp:
                await mcp.aclose()
            await llm.aclose()

        self._history.append(run)
        logger.info(
            "Job '%s' %s (cost=$%.4f, steps=%d)",
            run.job_name,
            run.status,
            run.cost_usd,
            run.steps,
        )
        return run

    async def run_loop(self) -> None:
        """Run all jobs on their configured intervals. Blocks forever."""
        if not self._jobs:
            logger.warning("No enabled jobs — scheduler idle.")
            return

        self._running = True
        last_run: dict[str, float] = {}
        logger.info("Scheduler started with %d job(s)", len(self._jobs))

        while self._running:
            now = time.monotonic()
            for job in self._jobs:
                interval = _parse_interval_seconds(job.cron)
                last = last_run.get(job.name, 0.0)
                if now - last >= interval:
                    last_run[job.name] = now
                    try:
                        await self.run_once(job)
                    except Exception:  # noqa: BLE001
                        logger.exception("Scheduler: job '%s' crashed", job.name)
            await asyncio.sleep(min(30, min(
                (_parse_interval_seconds(j.cron) for j in self._jobs), default=60
            )))

    def stop(self) -> None:
        self._running = False
