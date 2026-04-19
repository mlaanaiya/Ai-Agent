# Life Assistant — user guide

This document explains the 16 life-management features the agent can run
against your Google Drive. Nothing is hard-coded into the Python code: each
feature is either (a) a scheduled prompt in `config/jobs.json` or (b) a
quick-log HTTP endpoint backed by an LLM prompt. Change anything you don't
like by editing the prompt.

## Setup (once)

```bash
# 1. Configure .env (Gemini API key + Drive folder ID + service account JSON)
cp .env.example .env
# edit .env

# 2. Create the folder structure + seed log files in Drive
python scripts/setup_life_folders.py

# 3. Copy the example jobs and enable/disable what you want
cp config/jobs.example.json config/jobs.json

# 4. Start everything
ai-agent-web        # web UI — one terminal
ai-agent-scheduler  # cron-like runner — another terminal
```

The folder structure the setup script creates:

```
Health/Meds              + meds-log.jsonl
Health/Labs              + lab-results.csv
Health/Vitals            + vitals-log.jsonl
Health/Appointments
Money/Statements
Money/Receipts
Money/Expenses           + expenses.csv
Money/Subscriptions      + subscriptions.csv
Money/Budgets            + budget.json
Money/Goals              + savings-goals.json
Dev/Snippets
Dev/Standups
Dev/Learning             + reading-list.jsonl
Life/Briefings
Life/Notes
Life/Todos               + todos.jsonl
Reports
```

## The 16 features

### Health (tuned for post-kidney-transplant follow-up)

| # | Feature | Trigger | What it does |
|---|---|---|---|
| 1 | **Morning-briefing** | daily | Combines today's todos, meds, appointments, recent files into one 10-bullet briefing saved to `Life/Briefings/`. |
| 2 | **Med reminder (morning)** | daily | Appends a pending dose to `meds-log.jsonl`, reports last 7-day adherence. |
| 3 | **Med reminder (evening)** | daily | Same for the evening dose. |
| 4 | **Lab results parser** | every 6h | Parses any new PDF in `Health/Labs/` → appends rows to `lab-results.csv`, flags abnormal values. |
| 5 | **Appointment prep** | daily | If an appointment is scheduled in the next 48h, assembles a 1-page prep note (recent labs, vitals, adherence, questions). |
| 6 | **Hydration reminder** | every 4h (disabled by default) | Checks today's water log, prompts if under 1500 ml. |

### Money

| # | Feature | Trigger | What it does |
|---|---|---|---|
| 7 | **Bank statement parser** | every 12h | Parses new statements in `Money/Statements/` → appends to `expenses.csv`, moves processed files to `Processed/`. |
| 8 | **Budget alerts** | daily | Compares current-month spend to `budget.json`, flags categories over 80% with days left. |
| 9 | **Subscription auditor** | weekly | Detects recurring charges across 90 days, flags dormant ones, updates `subscriptions.csv`. |
| 10 | **Savings-goals progress** | weekly | Updates `savings-goals.json` based on net savings, writes encouragement. |

### Software engineer

| # | Feature | Trigger | What it does |
|---|---|---|---|
| 11 | **Daily standup generator** | daily | Summarises today's standup notes (or hints what to continue from yesterday). |
| 12 | **Learning digest** | weekly | Reads `reading-list.jsonl`, picks 3 articles to start with. |

### Daily life

| # | Feature | Trigger | What it does |
|---|---|---|---|
| 13 | **Meeting notes organizer** | daily | Reads `raw-*.md` in `Life/Notes/`, produces cleaned `organized-*.md`. |
| 14 | **Task extractor** | daily | Scans recent notes for TODOs/commitments, appends to `todos.jsonl`. |

### Weekly reports

| # | Feature | Trigger | What it does |
|---|---|---|---|
| 15 | **Weekly health report** | weekly | One-page summary saved to `Reports/health-week-YYYY-WW.md`. |
| 16 | **Weekly money report** | weekly | One-page summary saved to `Reports/money-week-YYYY-WW.md`. |

## Quick-log endpoints (phone shortcuts)

For anything you want to log in 2 seconds without opening the web UI, the
server exposes 5 endpoints. Set a `QUICKLOG_TOKEN` in `.env` and send it
as the `X-Quicklog-Token` header.

### 1. Log a medication as taken

```bash
curl -X POST http://your-host:8000/api/quicklog/med \
  -H 'X-Quicklog-Token: YOUR_TOKEN' \
  -H 'Content-Type: application/json' \
  -d '{"slot": "morning", "note": "tacrolimus + mycophenolate"}'
```

### 2. Log a vital (BP, weight, water, heart rate)

```bash
curl -X POST http://your-host:8000/api/quicklog/vitals \
  -H 'X-Quicklog-Token: YOUR_TOKEN' \
  -H 'Content-Type: application/json' \
  -d '{"type": "bp", "systolic": 125, "diastolic": 80}'

curl -X POST http://your-host:8000/api/quicklog/vitals \
  -H 'X-Quicklog-Token: YOUR_TOKEN' \
  -H 'Content-Type: application/json' \
  -d '{"type": "water", "value": 250, "unit": "ml"}'
```

### 3. Log an expense

```bash
curl -X POST http://your-host:8000/api/quicklog/expense \
  -H 'X-Quicklog-Token: YOUR_TOKEN' \
  -H 'Content-Type: application/json' \
  -d '{"amount": 12.50, "currency": "EUR", "category": "groceries", "merchant": "Carrefour"}'
```

### 4. Add a todo

```bash
curl -X POST http://your-host:8000/api/quicklog/todo \
  -H 'X-Quicklog-Token: YOUR_TOKEN' \
  -H 'Content-Type: application/json' \
  -d '{"text": "Renew carte vitale", "due": "2026-05-01"}'
```

### 5. Save an article to the reading list

```bash
curl -X POST http://your-host:8000/api/quicklog/reading \
  -H 'X-Quicklog-Token: YOUR_TOKEN' \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://example.com/article", "title": "Rust async primer", "tag": "rust"}'
```

### iOS Shortcuts / Android Tasker

Bind one "Shortcut" (iOS) or Tasker action (Android) per endpoint.
Recommended home-screen widgets:

- "Meds taken — morning" → POST to `/api/quicklog/med` with `slot=morning`.
- "Meds taken — evening" → same with `slot=evening`.
- "Log BP" → prompt for 2 numbers, POST to `/api/quicklog/vitals`.
- "+250 ml water" → POST to `/api/quicklog/vitals` with fixed payload.
- "Expense" → prompt for amount + merchant → POST.
- "+ Todo" → prompt for text → POST.
- "Save for later" → share-sheet URL → POST.

## How to change the behaviour

Everything is data:

- **Prompt tuning.** Edit `config/jobs.json`. Reload requires restarting
  `ai-agent-scheduler`.
- **Change schedule.** `"cron"` accepts `hourly`, `daily`, `weekly`, `30m`,
  `4h`, `90s`.
- **Disable a job.** Set `"enabled": false`.
- **Add a new job.** Append an object to the `jobs` array; no code change
  needed. The agent figures out which Drive tools to use from your prompt.
- **Change a quick-log payload.** Edit the prompt strings in
  `src/web/app.py` under the `quicklog_*` handlers.

## Safety & privacy

- The agent never sees your Drive credentials; the service account key stays
  with the MCP server.
- Everything is sandboxed to `DRIVE_ROOT_FOLDER_ID`. The agent can't touch
  anything outside it.
- Every MCP tool call is audited to `./audit/mcp-drive.jsonl`.
- The quick-log endpoints require a token you control. Rotate it by
  changing `QUICKLOG_TOKEN` and restarting the web server.
- Medical-record IDs and full card numbers are redacted in summaries by the
  system prompt.
- Want zero cloud LLM calls? Set `LLM_BACKEND=ollama`. Gemini never sees
  your data in that mode.

## Troubleshooting

- **A job fails with "file not found":** run
  `python scripts/setup_life_folders.py` once to create the expected
  structure and seed files.
- **Lab parser doesn't extract values:** Gemini Flash handles most PDFs via
  Drive's built-in text export. For scanned PDFs, you'll need to OCR them
  first (Drive can do this — right-click → Open with → Google Docs).
- **Statements have weird formats:** tune the bank-statement-parser prompt
  in `config/jobs.json` with an example of your bank's layout.
- **Budget alerts too noisy:** change `80%` in the prompt to `90%`, or set
  `"enabled": false`.
