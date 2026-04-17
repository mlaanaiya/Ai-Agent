# AI Agent — Sovereign, free, MCP-native Drive assistant

100% free-stack implementation of the architecture described in the design
note of 15 April 2026: an autonomous document-processing agent built on four
independent pillars, with **zero paid API keys**.

| Pillar | What it does | Cost |
| --- | --- | --- |
| **Orchestrator** — [OpenClaw](https://openclaw.ai) | Local-first Gateway, ReAct loop, short-term memory, MCP client, multi-channel inbox | Free (OSS) |
| **LLM** — [Ollama](https://ollama.com) | Local inference, no data leaves the host, OpenAI-compatible API | Free |
| **MCP gateway** — *this repo* | Exposes a Google Drive sandbox as audited MCP tools | Free (OSS) |
| **Document store** — Google Drive | Source of truth for inputs and deliverables | Free tier |

All LLM inference runs locally via Ollama. No OpenRouter, no API key,
no per-token cost, no data sent to third parties.

## Why this split

- **Zero cost on the model.** Ollama runs locally; switch models with a
  single config change.
- **Zero-trust on the data.** The LLM never sees Google credentials.
  Prompts and responses never leave the host.
- **Maximum privacy.** No cloud LLM provider involved at all.
- **Extensibility by composition.** Add Slack, Notion, or a CRM by
  registering another MCP server with `openclaw mcp set` — no code change
  in the agent.

## Quickstart — Docker (recommended)

```bash
git clone <this repo> && cd Ai-Agent
cp .env.example .env
# Edit .env: set DRIVE_ROOT_FOLDER_ID
# Place the service account JSON at ./secrets/service_account.json

# Start everything:
docker compose up -d ollama
docker compose exec ollama ollama pull qwen2.5:7b   # one-time model download
docker compose up -d

# Web UI at http://localhost:8000
```

## Quickstart — local (no Docker)

```bash
# 1. Install Ollama: https://ollama.com
ollama pull qwen2.5:7b

# 2. Clone and install:
git clone <this repo> && cd Ai-Agent
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'

# 3. Configure:
cp .env.example .env
# Edit .env: set DRIVE_ROOT_FOLDER_ID
# Place service account JSON at ./secrets/service_account.json

# 4. Launch:
ai-agent-web                # Web UI → http://127.0.0.1:8000
# Or CLI:
ai-agent tools              # list MCP tools
ai-agent ask "List files."  # one-shot
ai-agent chat               # interactive REPL
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
- Config status indicator (Ollama / Drive / service account health check).

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

## MCP tools (9 total)

| Tool | Description |
|---|---|
| `list_files` | Enumerate files in a folder (default: sandbox root) |
| `search_drive` | Search by name across the sandbox (up to 3 levels deep) |
| `read_document` | Read the text content of a document (Docs/Sheets exported as text/CSV) |
| `save_file` | Create a new text file in the sandbox |
| `create_folder` | Create a subfolder |
| `get_metadata` | Get full file metadata (name, size, web link, description…) |
| `move_file` | Move a file to a different folder within the sandbox |
| `rename_file` | Rename a file |
| `delete_file` | Permanently delete a file (cannot delete the root) |

All tools enforce the folder sandbox, MIME allow-list, byte cap, and audit
logging. See `src/mcp_drive_server/server.py` for the full schema.

## Repository layout

```
src/
  mcp_drive_server/           # MCP Drive gateway  —  this is THE deliverable
    server.py                 # FastMCP app + audit hook
    drive.py                  # sandboxed Drive wrapper (policy lives here)
    audit.py                  # append-only JSONL audit
    config.py                 # pydantic settings
  orchestrator/               # fallback runner, only used without OpenClaw
    agent.py, ollama.py, mcp_client.py, memory.py, cli.py
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
tests/                        # 39 hermetic tests (no net, no creds)
docs/ARCHITECTURE.md
Dockerfile
docker-compose.yml
```

## Runtime flow

1. A user interacts via the web UI, CLI, or automation scheduler.
2. The orchestrator reads the system prompt, picks the Ollama model,
   and discovers the `drive-gateway` MCP server's tools.
3. On a tool call, the orchestrator forwards it to the MCP server.
4. The MCP server validates policy (sandbox, MIME allow-list, byte cap),
   calls Google Drive, logs the call to `audit/mcp-drive.jsonl`, and
   returns the result.
5. The orchestrator loops until the model produces a final answer, then
   displays it in the originating interface.

## Security model (summary)

- **Credential isolation.** The MCP server holds Google credentials.
  The LLM sees neither Google creds nor any API keys (there are none).
- **Local inference.** Ollama runs on-host. No prompts or responses leave
  the machine.
- **Folder sandbox.** `DriveClient._assert_in_sandbox` walks each file's
  parent chain and refuses anything whose ancestors don't include
  `DRIVE_ROOT_FOLDER_ID`.
- **MIME allow-list.** `DRIVE_ALLOWED_MIME_TYPES` caps readable types.
- **Byte cap.** Reads over `DRIVE_MAX_READ_BYTES` abort mid-download.
- **Audit trail.** Every MCP tool call is appended to
  `audit/mcp-drive.jsonl` with ts, args, status, duration, and error.

See `docs/ARCHITECTURE.md` for the full threat model.

## Recommended Ollama models

| Model | Size | Tool calling | Notes |
| --- | --- | --- | --- |
| `qwen2.5:7b` | ~4.4 GB | Yes | Good balance of quality and speed (default) |
| `llama3.1:8b` | ~4.7 GB | Yes | Strong general-purpose |
| `mistral:7b` | ~4.1 GB | Yes | Fast, efficient |
| `qwen2.5:14b` | ~8.7 GB | Yes | Higher quality, needs 12+ GB RAM |

Pull with: `ollama pull <model>`

## Tests

```bash
pytest -q
```

All 39 tests are offline (mocked HTTP, in-memory MCP transport, fake Drive)
— no API keys or network required.

## Docker

```bash
docker compose build
docker compose up -d ollama                        # start Ollama
docker compose exec ollama ollama pull qwen2.5:7b  # pull model (one-time)
docker compose up -d mcp-drive web                 # web UI at :8000
docker compose up -d scheduler                     # automated prompt runner
docker compose run --rm orchestrator chat          # CLI fallback
```

## Prerequisites (everything is free)

| # | Requirement | Cost |
|---|---|---|
| 1 | **Ollama** installed (host or Docker) | Free |
| 2 | An Ollama model pulled (e.g. `qwen2.5:7b`) | Free |
| 3 | **Google Cloud project** + Drive API enabled | Free |
| 4 | **Service account** JSON key | Free |
| 5 | **Google Drive folder** shared with the SA email | Free |
| 6 | A VPS or local machine with 8+ GB RAM | VPS cost if remote |

No paid API keys. No subscriptions. No per-token charges.
