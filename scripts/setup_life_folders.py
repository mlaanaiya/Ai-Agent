"""Create the Life Assistant folder structure + seed log files in Google Drive.

Run once after configuring .env + service account. Idempotent: re-running
only creates what's missing. Safe to run repeatedly.

Folder layout created under DRIVE_ROOT_FOLDER_ID:

    Health/
        Meds/          meds-log.jsonl  (append-only med dose log)
        Labs/          lab-results.csv (parsed lab values over time)
        Vitals/        vitals-log.jsonl (BP, weight, hydration)
        Appointments/  (drop appointment PDFs + agent writes prep notes here)
    Money/
        Statements/    (drop bank statement CSV/PDFs here)
        Receipts/      (drop receipt photos here)
        Expenses/      expenses.csv  (parsed expenses, one row per item)
        Subscriptions/ subscriptions.csv (detected recurring charges)
        Budgets/       budget.json   (monthly targets)
        Goals/         savings-goals.json
    Dev/
        Snippets/      (code snippets in .md files)
        Standups/      (daily standup notes)
        Learning/      reading-list.jsonl
    Life/
        Briefings/     (morning briefings land here)
        Notes/         (meeting notes, raw → organized)
        Todos/         todos.jsonl
    Reports/           (scheduled job outputs)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Make src/ importable when run directly from the repo.
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mcp_drive_server.config import DriveServerSettings  # noqa: E402
from mcp_drive_server.drive import DriveClient  # noqa: E402


FOLDER_TREE: dict[str, list[str]] = {
    "Health": ["Meds", "Labs", "Vitals", "Appointments"],
    "Money": ["Statements", "Receipts", "Expenses", "Subscriptions", "Budgets", "Goals"],
    "Dev": ["Snippets", "Standups", "Learning"],
    "Life": ["Briefings", "Notes", "Todos"],
    "Reports": [],
}

SEED_FILES: dict[tuple[str, str], tuple[str, str]] = {
    # (parent_path, filename): (mime_type, initial_content)
    ("Health/Meds", "meds-log.jsonl"): (
        "application/jsonl",
        "",
    ),
    ("Health/Labs", "lab-results.csv"): (
        "text/csv",
        "date,test,value,unit,reference_range,flag\n",
    ),
    ("Health/Vitals", "vitals-log.jsonl"): (
        "application/jsonl",
        "",
    ),
    ("Money/Expenses", "expenses.csv"): (
        "text/csv",
        "date,amount,currency,category,merchant,note,source\n",
    ),
    ("Money/Subscriptions", "subscriptions.csv"): (
        "text/csv",
        "merchant,amount,currency,cadence,last_seen,status,note\n",
    ),
    ("Money/Budgets", "budget.json"): (
        "application/json",
        json.dumps(
            {
                "month": "",
                "currency": "EUR",
                "categories": {
                    "groceries": 400,
                    "dining": 150,
                    "transport": 100,
                    "utilities": 200,
                    "subscriptions": 80,
                    "health": 100,
                    "other": 200,
                },
            },
            indent=2,
        ) + "\n",
    ),
    ("Money/Goals", "savings-goals.json"): (
        "application/json",
        json.dumps(
            {
                "currency": "EUR",
                "goals": [
                    {"name": "emergency-fund", "target": 6000, "current": 0},
                    {"name": "vacation-2026", "target": 2000, "current": 0},
                ],
            },
            indent=2,
        ) + "\n",
    ),
    ("Dev/Learning", "reading-list.jsonl"): (
        "application/jsonl",
        "",
    ),
    ("Life/Todos", "todos.jsonl"): (
        "application/jsonl",
        "",
    ),
}


def main() -> int:
    settings = DriveServerSettings()
    settings.ensure_valid()
    client = DriveClient(
        service_account_file=settings.service_account_file,
        root_folder_id=settings.root_folder_id,
        allowed_mime_types=settings.allowed_mime_types,
        max_read_bytes=settings.max_read_bytes,
    )

    # Build a path → id map as we go.
    path_to_id: dict[str, str] = {"": settings.root_folder_id}

    for top, subs in FOLDER_TREE.items():
        top_id = _ensure_folder(client, top, parent_id=settings.root_folder_id)
        path_to_id[top] = top_id
        for sub in subs:
            sub_id = _ensure_folder(client, sub, parent_id=top_id)
            path_to_id[f"{top}/{sub}"] = sub_id

    # Seed files.
    for (parent_path, fname), (mime, content) in SEED_FILES.items():
        parent_id = path_to_id[parent_path]
        existing = client.find_file_by_name(fname, parent_id=parent_id)
        if existing is not None:
            print(f"  exists:  {parent_path}/{fname}")
            continue
        client.save_file(
            name=fname, content=content, folder_id=parent_id, mime_type=mime
        )
        print(f"  created: {parent_path}/{fname}")

    print("\nDone. Folder structure ready.")
    print("Share key folder IDs with the agent via the system prompt or .env:")
    for path, fid in path_to_id.items():
        if path:
            print(f"  {path:30s}  {fid}")
    return 0


def _ensure_folder(client: DriveClient, name: str, *, parent_id: str) -> str:
    existing = client.find_file_by_name(name, parent_id=parent_id)
    if existing is not None:
        print(f"  exists:  {name}")
        return existing["id"]
    created = client.create_folder(name, parent_id=parent_id)
    print(f"  created: {name}")
    return created.id


if __name__ == "__main__":
    sys.exit(main())
