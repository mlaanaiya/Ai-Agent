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

Additional deployment options now included in the repo:

- `LLM_BACKEND=openai` for an OpenAI-compatible remote model API
- a second `enterprise-gateway` MCP server for approved internal tools
- a Telegram webhook channel with whitelist by Telegram `user_id` / `chat_id`

## Why this split

- **Zero cost on the model.** Gemini free tier has generous daily limits;
  Ollama runs locally as a fallback. Switch backends with a single env var.
- **Zero-trust on the data.** The LLM never sees Google credentials.
- **Privacy option.** Set `LLM_BACKEND=ollama` for fully local inference
  where no data leaves the host.
- **Extensibility by composition.** Add Slack, Notion, or a CRM by
  registering another MCP server with `openclaw mcp set` — no code change
  in the agent.
- **Least-privilege enterprise actions.** The enterprise MCP server exposes
  explicit, auditable tools only: approved policy reads and structured
  request queuing.

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

## Quickstart — Telegram + multi-MCP

```bash
cp .env.example .env
# Edit .env:
#   TELEGRAM_BOT_TOKEN=<bot token>
#   TELEGRAM_WEBHOOK_SECRET=<shared secret>
#   TELEGRAM_ALLOWED_USER_IDS=123456789
#   MCP_SERVERS_CONFIG_FILE=./config/mcp_servers.example.json

ai-agent-web
# Expose POST /api/telegram/webhook over HTTPS, then register the webhook
# in Telegram with the same secret token.
```

Register both MCP servers in OpenClaw with:

```bash
./scripts/register-openclaw.sh --with-enterprise
```

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

## MCP tools

### Drive gateway (9 tools)

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

### Enterprise gateway (4 tools)

| Tool | Description |
|---|---|
| `enterprise_list_policies` | List approved internal policies/runbooks from a whitelisted directory |
| `enterprise_read_policy` | Read one approved policy by slug |
| `enterprise_create_request` | Queue a structured enterprise request for human follow-up |
| `enterprise_list_requests` | List recently queued enterprise requests |

Both gateways enforce explicit policy boundaries and append every tool call to
an audit log. See `src/mcp_drive_server/server.py` and
`src/mcp_enterprise_server/server.py`.

## Repository layout

```
src/
  mcp_drive_server/           # MCP Drive gateway  —  this is THE deliverable
    server.py                 # FastMCP app + audit hook
    drive.py                  # sandboxed Drive wrapper (policy lives here)
    audit.py                  # append-only JSONL audit
    config.py                 # pydantic settings
  mcp_enterprise_server/      # least-privilege enterprise MCP gateway
    server.py                 # policy docs + request queue tools
    store.py                  # path hardening and request validation
    config.py                 # pydantic settings
  orchestrator/               # fallback runner, only used without OpenClaw
    agent.py, gemini.py, ollama.py, openai_compatible.py
    llm.py, mcp_client.py, memory.py, cli.py
  web/                        # FastAPI web interface (dark theme, SSE streaming)
    app.py, session_store.py, telegram.py, schemas.py, templates/, static/
  automation/                 # Scheduled prompt runner + webhook trigger
    scheduler.py              # cron-like loop, job definitions, history
config/
  SOUL.md                     # OpenClaw personality (document analyst)
  AGENTS.md                   # OpenClaw operating rules
  openclaw.config.json5       # OpenClaw config snippet
  mcp_servers.example.json    # local multi-MCP fallback config
  enterprise_policies/        # approved runbooks exposed by enterprise MCP
  jobs.example.json           # sample scheduled jobs
scripts/
  register-openclaw.sh        # idempotent `openclaw mcp set` wrapper
tests/                        # 56 hermetic tests (no net, no creds)
docs/ARCHITECTURE.md
Dockerfile
docker-compose.yml
```

## Runtime flow

1. A user interacts via the web UI, CLI, automation scheduler, or Telegram bot.
2. The orchestrator calls `build_llm()` to select the configured backend
   (Gemini, Ollama, or an OpenAI-compatible remote API).
3. The orchestrator discovers one or more MCP servers and exposes their tools
   as a single tool set to the model.
4. On a tool call, the orchestrator dispatches it to the matching MCP server.
5. The Drive MCP server enforces sandbox, MIME allow-list, and byte caps;
   the enterprise MCP server restricts reads to approved policy files and
   writes actions only to a structured request outbox.
6. The orchestrator loops until the model produces a final answer, then
   displays it in the originating interface.

## Security model (summary)

- **Credential isolation.** The MCP server holds Google credentials.
  The LLM never sees Google creds. Gemini API key is used only for
  LLM inference — never exposed to the model itself.
- **Telegram whitelist.** The webhook refuses any message whose Telegram
  `user_id` / `chat_id` is outside the configured allow-list, and private
  chats are enforced by default.
- **Local option.** Set `LLM_BACKEND=ollama` for fully local inference
  where no prompts or responses leave the machine.
- **Folder sandbox.** `DriveClient._assert_in_sandbox` walks each file's
  parent chain and refuses anything whose ancestors don't include
  `DRIVE_ROOT_FOLDER_ID`.
- **Enterprise least privilege.** Internal runbooks are only readable from
  `ENTERPRISE_POLICIES_DIR`; write operations only enqueue JSON requests in
  `ENTERPRISE_REQUEST_OUTBOX`.
- **MIME allow-list.** `DRIVE_ALLOWED_MIME_TYPES` caps readable types.
- **Byte cap.** Reads over `DRIVE_MAX_READ_BYTES` abort mid-download.
- **Audit trail.** Every MCP tool call is appended to
  `audit/mcp-drive.jsonl` or `audit/mcp-enterprise.jsonl` with ts, args,
  status, duration, and error.

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

### OpenAI-compatible remote API

```bash
LLM_BACKEND=openai
OPENAI_API_KEY=...
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4.1-mini
```

`OPENAI_BASE_URL` can also target a compatible gateway or proxy.

## Tests

```bash
pytest -q
```

All 56 tests are offline (mocked HTTP, in-memory MCP transport, fake Drive /
enterprise stores) — no API keys or network required.

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
