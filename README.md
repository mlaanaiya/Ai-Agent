# AI Agent — Sovereign, free, MCP-native Drive assistant

100% free-stack implementation of the architecture described in the design
note of 15 April 2026: an autonomous document-processing agent built on four
independent pillars, with **zero paid API keys**.

| Pillar | What it does | Cost |
| --- | --- | --- |
| **Orchestrator** — [OpenClaw](https://openclaw.ai) | Local-first Gateway, ReAct loop, short-term memory, MCP client, multi-channel inbox | Free (OSS) |
| **LLM** — [Gemini 2.0 Flash](https://ai.google.dev) | Google's free-tier LLM with strong tool-calling, 15 req/min, 1M tokens/day | Free |
| **LLM fallback** — [Ollama](https://ollama.com) | Local inference, no data leaves the host, OpenAI-compatible API | Free |
| **MCP gateway** — *this repo* | Exposes a Google Drive sandbox as audited MCP tools | Free (OSS) |
| **Document store** — Google Drive | Source of truth for inputs and deliverables | Free tier |

Default LLM: **Gemini 2.0 Flash** (free tier, 15 req/min, 1M tokens/day).
Fallback: **Ollama** (100% local, zero network). Switch with `LLM_BACKEND=ollama`.

## Why this split

- **Zero cost on the model.** Gemini free tier has generous daily limits;
  Ollama runs locally as a fallback. Switch backends with a single env var.
- **Zero-trust on the data.** The LLM never sees Google credentials.
- **Privacy option.** Set `LLM_BACKEND=ollama` for fully local inference
  where no data leaves the host.
- **Extensibility by composition.** Add Slack, Notion, or a CRM by
  registering another MCP server with `openclaw mcp set` — no code change
  in the agent.

## Quickstart — Gemini (recommended, fastest)

```bash
git clone <this repo> && cd Ai-Agent
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'

cp .env.example .env
# Edit .env:
#   GEMINI_API_KEY=<your free key from https://aistudio.google.com/apikey>
#   DRIVE_ROOT_FOLDER_ID=<your folder id>
# Place service account JSON at ./secrets/service_account.json

ai-agent-web                # Web UI → http://127.0.0.1:8000
```

## Quickstart — Ollama (fully local, no network)

```bash
# 1. Install Ollama: https://ollama.com
ollama pull qwen2.5:7b

# 2. Clone and install:
git clone <this repo> && cd Ai-Agent
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'

# 3. Configure:
cp .env.example .env
# Edit .env:
#   LLM_BACKEND=ollama
#   DRIVE_ROOT_FOLDER_ID=<your folder id>
# Place service account JSON at ./secrets/service_account.json

# 4. Launch:
ai-agent-web                # Web UI → http://127.0.0.1:8000
# Or CLI:
ai-agent tools              # list MCP tools
ai-agent ask "List files."  # one-shot
ai-agent chat               # interactive REPL
```

## Quickstart — Docker

```bash
git clone <this repo> && cd Ai-Agent
cp .env.example .env
# Edit .env: set GEMINI_API_KEY + DRIVE_ROOT_FOLDER_ID
# Place the service account JSON at ./secrets/service_account.json

# If using Ollama backend:
docker compose up -d ollama
docker compose exec ollama ollama pull qwen2.5:7b   # one-time model download

docker compose up -d
# Web UI at http://localhost:8000
```

## Quickstart — Web UI

The project ships a full-featured web interface (dark theme, live streaming,
tool call cards, audit panel, multi-session). No separate build step.

```bash
ai-agent-web                              # → http://127.0.0.1:8000
# Or with a custom bind:
HOST=0.0.0.0 PORT=8080 ai-agent-web
```

**Features**:
- Dark-themed single-page app (Tailwind + vanilla JS, zero build step).
- Server-Sent Events streaming: see tool calls, arguments, and results
  appear live as the agent works.
- Multi-session sidebar with per-session memory.
- Right panel showing MCP tools discovered from the gateway + live audit
  log refresh.
- Suggested prompts for quick-start.
- Config status indicator (LLM backend / Drive / service account health check).
- Markdown rendering with syntax highlighting (marked.js + highlight.js).
- Keyboard shortcuts (Ctrl+N, Ctrl+E, Ctrl+/, Escape).
- Conversation export to text file.
- Toast notification system.
- Mobile responsive with slide-out sidebar.

## Quickstart — automation (scheduled prompts)

```bash
cp config/jobs.example.json config/jobs.json   # customise prompts + schedules
ai-agent-scheduler                             # daemon — runs jobs on schedule
ai-agent-scheduler --run-once daily-summary    # run a single job then exit
```

Or via the web UI webhook (`POST /api/webhook`):

```bash
curl -X POST http://localhost:8000/api/webhook \
     -H "Content-Type: application/json" \
     -d '{"prompt": "List files in the sandbox."}'
```

## MCP tools (13 total)

| Tool | Description |
|---|---|
| `list_files` | Enumerate files in a folder (default: sandbox root) |
| `list_recent_files` | List recently-modified files (newest first) |
| `search_drive` | Search by name across the sandbox (up to 3 levels deep) |
| `find_file_by_name` | Exact-name lookup in one folder (returns null if missing) |
| `read_document` | Read the text content of a document (Docs/Sheets exported as text/CSV) |
| `save_file` | Create a new text file in the sandbox |
| `append_to_file` | Append a line/row to an existing text/CSV/JSONL file (logs!) |
| `overwrite_file` | Replace a file's entire content (snapshots/dashboards) |
| `create_folder` | Create a subfolder |
| `get_metadata` | Get full file metadata (name, size, web link, description…) |
| `move_file` | Move a file to a different folder within the sandbox |
| `rename_file` | Rename a file |
| `delete_file` | Permanently delete a file (cannot delete the root) |

All tools enforce the folder sandbox, MIME allow-list, byte cap, and audit
logging. See `src/mcp_drive_server/server.py` for the full schema.

## Life Assistant (16 ready-to-use features)

This project is a complete Life Assistant — medications, labs, finances,
subscriptions, savings goals, standups, learning, todos, morning briefings,
and more. All 16 features are pre-configured scheduled prompts +
quick-log endpoints for phone shortcuts.

See [`docs/LIFE_ASSISTANT.md`](docs/LIFE_ASSISTANT.md) for the full guide.

```bash
# One-time setup:
python scripts/setup_life_folders.py   # create Drive folders + seed files
cp config/jobs.example.json config/jobs.json

# Run:
ai-agent-web         # web UI + HTTP endpoints
ai-agent-scheduler   # runs the 16 jobs on schedule
```

## Repository layout

```
src/
  mcp_drive_server/           # MCP Drive gateway  —  this is THE deliverable
    server.py                 # FastMCP app + audit hook
    drive.py                  # sandboxed Drive wrapper (policy lives here)
    audit.py                  # append-only JSONL audit
    config.py                 # pydantic settings
  orchestrator/               # fallback runner, only used without OpenClaw
    agent.py, gemini.py, ollama.py, llm.py, mcp_client.py, memory.py, cli.py
  web/                        # FastAPI web interface (dark theme, SSE streaming)
    app.py, session_store.py, schemas.py, templates/, static/
  automation/                 # Scheduled prompt runner + webhook trigger
    scheduler.py              # cron-like loop, job definitions, history
config/
  SOUL.md                     # OpenClaw personality (document analyst)
  AGENTS.md                   # OpenClaw operating rules
  openclaw.config.json5       # OpenClaw config snippet
  jobs.example.json           # sample scheduled jobs
scripts/
  register-openclaw.sh        # idempotent `openclaw mcp set` wrapper
  setup_life_folders.py       # one-shot folder structure + seed files
tests/                        # 59 hermetic tests (no net, no creds)
docs/
  ARCHITECTURE.md
  LIFE_ASSISTANT.md           # user guide — 16 features + quick-log endpoints
Dockerfile
docker-compose.yml
```

## Runtime flow

1. A user interacts via the web UI, CLI, or automation scheduler.
2. The orchestrator calls `build_llm()` to select the configured backend
   (Gemini or Ollama) and discovers the `drive-gateway` MCP server's tools.
3. On a tool call, the orchestrator forwards it to the MCP server.
4. The MCP server validates policy (sandbox, MIME allow-list, byte cap),
   calls Google Drive, logs the call to `audit/mcp-drive.jsonl`, and
   returns the result.
5. The orchestrator loops until the model produces a final answer, then
   displays it in the originating interface.

## Security model (summary)

- **Credential isolation.** The MCP server holds Google credentials.
  The LLM never sees Google creds. Gemini API key is used only for
  LLM inference — never exposed to the model itself.
- **Local option.** Set `LLM_BACKEND=ollama` for fully local inference
  where no prompts or responses leave the machine.
- **Folder sandbox.** `DriveClient._assert_in_sandbox` walks each file's
  parent chain and refuses anything whose ancestors don't include
  `DRIVE_ROOT_FOLDER_ID`.
- **MIME allow-list.** `DRIVE_ALLOWED_MIME_TYPES` caps readable types.
- **Byte cap.** Reads over `DRIVE_MAX_READ_BYTES` abort mid-download.
- **Audit trail.** Every MCP tool call is appended to
  `audit/mcp-drive.jsonl` with ts, args, status, duration, and error.

See `docs/ARCHITECTURE.md` for the full threat model.

## LLM backends

### Gemini 2.0 Flash (default)

Free tier: 15 req/min, 1M tokens/day, 1500 req/day.
Get a key at https://aistudio.google.com/apikey — set `GEMINI_API_KEY` in `.env`.

### Ollama (local fallback)

| Model | Size | Tool calling | Notes |
| --- | --- | --- | --- |
| `qwen2.5:7b` | ~4.4 GB | Yes | Good balance of quality and speed (default) |
| `llama3.1:8b` | ~4.7 GB | Yes | Strong general-purpose |
| `mistral:7b` | ~4.1 GB | Yes | Fast, efficient |
| `qwen2.5:14b` | ~8.7 GB | Yes | Higher quality, needs 12+ GB RAM |

Pull with: `ollama pull <model>`

Set `LLM_BACKEND=ollama` in `.env` to use Ollama instead of Gemini.

## Tests

```bash
pytest -q
```

All 59 tests are offline (mocked HTTP, in-memory MCP transport, fake Drive)
— no API keys or network required.

## Prerequisites (everything is free)

| # | Requirement | Cost |
|---|---|---|
| 1 | **Gemini API key** (free at aistudio.google.com) | Free |
| 2 | **Google Cloud project** + Drive API enabled | Free |
| 3 | **Service account** JSON key | Free |
| 4 | **Google Drive folder** shared with the SA email | Free |
| 5 | A VPS or local machine | VPS cost if remote |

**Or with Ollama** (no API key at all): install Ollama + pull a model,
set `LLM_BACKEND=ollama`. Needs 8+ GB RAM.

No paid API keys. No subscriptions. No per-token charges.
