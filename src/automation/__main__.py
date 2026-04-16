"""Run the scheduler daemon.

    $ python -m automation                              # uses default jobs.json
    $ python -m automation --jobs ./my-jobs.json        # custom jobs file
    $ python -m automation --run-once "daily-summary"   # run one job then exit
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

from orchestrator.config import OrchestratorSettings

from .scheduler import Scheduler, load_jobs


def main() -> int:
    logging.basicConfig(
        level=os.environ.get("AGENT_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    jobs_path_env = os.environ.get("AUTOMATION_JOBS_FILE", "./config/jobs.json")
    run_once_name = None

    # Simple argv parsing (no extra dependency).
    args = sys.argv[1:]
    while args:
        arg = args.pop(0)
        if arg == "--jobs" and args:
            jobs_path_env = args.pop(0)
        elif arg == "--run-once" and args:
            run_once_name = args.pop(0)

    settings = OrchestratorSettings()
    settings.ensure_valid()

    jobs = load_jobs(Path(jobs_path_env))
    if not jobs:
        logging.error("No jobs found in %s", jobs_path_env)
        return 1

    scheduler = Scheduler(settings, jobs)

    if run_once_name:
        target = next((j for j in jobs if j.name == run_once_name), None)
        if target is None:
            logging.error("Job '%s' not found in %s", run_once_name, jobs_path_env)
            return 1
        result = asyncio.run(scheduler.run_once(target))
        print(f"[{result.status}] {result.job_name}: {result.result_text[:200]}")
        return 0 if result.status == "ok" else 1

    asyncio.run(scheduler.run_loop())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
