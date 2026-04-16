"""Tests for the automation scheduler."""

from __future__ import annotations

import json
from pathlib import Path

from automation.scheduler import JobDefinition, Scheduler, load_jobs, _parse_interval_seconds


def test_parse_interval_seconds() -> None:
    assert _parse_interval_seconds("hourly") == 3600
    assert _parse_interval_seconds("daily") == 86400
    assert _parse_interval_seconds("weekly") == 604800
    assert _parse_interval_seconds("5m") == 300
    assert _parse_interval_seconds("2h") == 7200
    assert _parse_interval_seconds("30s") == 30
    assert _parse_interval_seconds("120") == 120


def test_load_jobs(tmp_path: Path) -> None:
    jobs_file = tmp_path / "jobs.json"
    jobs_file.write_text(json.dumps({
        "jobs": [
            {"name": "j1", "prompt": "do stuff", "cron": "hourly", "enabled": True},
            {"name": "j2", "prompt": "do more", "cron": "daily", "enabled": False},
        ]
    }))
    jobs = load_jobs(jobs_file)
    assert len(jobs) == 2
    assert jobs[0].name == "j1"
    assert jobs[0].cron == "hourly"
    assert jobs[1].enabled is False


def test_load_jobs_missing_file(tmp_path: Path) -> None:
    assert load_jobs(tmp_path / "nope.json") == []


def test_scheduler_filters_disabled_jobs() -> None:
    from unittest.mock import MagicMock
    settings = MagicMock()
    jobs = [
        JobDefinition(name="on", prompt="p", cron="daily", enabled=True),
        JobDefinition(name="off", prompt="p", cron="daily", enabled=False),
    ]
    scheduler = Scheduler(settings, jobs)
    assert len(scheduler._jobs) == 1
    assert scheduler._jobs[0].name == "on"
