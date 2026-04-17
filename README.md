# AI Agent — Sovereign, MCP-native Drive assistant

First stable implementation of the architecture described in the design note
of 15 April 2026: an autonomous document-processing agent built on four
independent pillars.

| Pillar | What it does | Where it lives |
| --- | --- | --- |
| **Orchestrator** — [OpenClaw](https://openclaw.ai) | Local-first Gateway, ReAct loop, short-term memory, MCP client, multi-channel inbox | External (installed via its own CLI) |
| **LLM gateway** — [OpenRouter](https://openrouter.ai) | Routes each request to the best/cheapest model | Configured inside OpenClaw |
| **MCP gateway** — *this repo* | Exposes a Google Drive sandbox as audited MCP tools | `src/mcp_drive_server/` |
| **Document store** — Google Drive | Source of truth for inputs and deliverables | External |

The **only component this repository ships** is the MCP Drive gateway (the
"Serveur MCP sur Gandi" of the design note). Everything else — the agent
loop, model routing, personality, multi-agent coordination — is OpenClaw,
configured via `config/SOUL.md`, `config/AGENTS.md`, and
`config/openclaw.config.json5`.

A tiny fallback orchestrator (`src/orchestrator/`) is also bundled for CI,
air-gapped demos, or bootstrapping before OpenClaw is installed. It speaks
the same MCP server, just with a much thinner agent loop.

## Why this split

- **Zero vendor lock-in on the model.** OpenRouter picks the model; flip a
  config value to change it.
- **Zero-trust on the data.** The LLM (and OpenClaw itself) never see
  Google credentials. The MCP server holds the service-account key and
  enforces the sandbox on every call.
- **FinOps controls.** OpenRouter reports per-call cost; the fallback
  runner has `OPENROUTER_MAX_COST_USD` as a hard cap.
- **Extensibility by composition.** Add Slack, Notion, or a CRM by
  registering another MCP server with `openclaw mcp set` — no code change
  in the agent.

## Quickstart — OpenClaw deployment (reference)

Follow this path if you want the architecture from the design note end to
end.

```bash
# 1. Install OpenClaw (see https://openclaw.ai for the current installer).
# 2. Onboard with OpenRouter:
openclaw onboard --auth-choice openrouter-api-key

# 3. Clone this repo and install the Drive gateway's Python deps.
git clone <this repo> && cd Ai-Agent
python -m venv .venv && source .venv/bin/activate
pip install -e .

# 4. Provision Google Drive:
#    * Create a service account in Google Cloud, download its JSON key,
#      save it as ./secrets/service_account.json
#    * Share the target Drive folder with the service-account email.
#    * Export its folder id:
export DRIVE_ROOT_FOLDER_ID=1AbC...xyz

# 5. Register the MCP server with OpenClaw:
./scripts/register-openclaw.sh            # local (stdio)
./scripts/register-openclaw.sh --remote   # Gandi-hosted (streamable-http)

# 6. Point OpenClaw at the SOUL.md / AGENTS.md in this repo (or merge the
#    snippet from config/openclaw.config.json5 into your OpenClaw config).

# 7. Start chatting via whichever channel you set up in OpenClaw (WhatsApp,
#    Telegram, Slack, local terminal…). Try:
#        "Résume le compte-rendu Q3 du dossier Stratégie."
```

## Quickstart — Web UI (recommended for interactive use)

The project ships a full-featured web interface (dark theme, live streaming,
tool call cards, audit panel, multi-session). No separate build step.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env    # fill OPENROUTER_API_KEY and DRIVE_ROOT_FOLDER_ID
# Place the service account JSON at ./secrets/service_account.json

# Launch the web UI:
ai-agent-web                              # → http://127.0.0.1:8000
# Or with a custom bind:
HOST=0.0.0.0 PORT=8080 ai-agent-web
```

**Features**:
- Dark-themed single-page app (Tailwind + vanilla JS, zero build step).
- Server-Sent Events streaming: see tool calls, arguments, and results
  appear live as the agent works.
- Multi-session sidebar with per-session memory and cost tracking.
- Right panel showing MCP tools discovered from the gateway + live audit
  log refresh.
- Suggested prompts for quick-start.
- Config status indicator (API key / Drive / service account health check).

## Quickstart — Telegram bot

```bash
# 1. Create a bot via @BotFather on Telegram → copy the token
export TELEGRAM_BOT_TOKEN=<token>

# 2. Launch (uses the same .env for OpenRouter + Drive)
ai-agent-telegram
```

The bot provides per-chat sessions with persistent memory. Tool calls are
shown as inline status updates that get edited in real-time. Commands:
`/start`, `/reset`, `/tools`, `/cost`.

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

## Quickstart — CLI fallback (no browser needed)

```bash
ai-agent tools                             # list MCP tools
ai-agent ask "Summarise the Q3 notes."     # one-shot
ai-agent chat                              # interactive REPL
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
    agent.py, openrouter.py, mcp_client.py, memory.py, cli.py
  web/                        # FastAPI web interface (dark theme, SSE streaming)
    app.py, session_store.py, schemas.py, templates/, static/
  telegram_bot/               # Telegram integration (per-chat sessions)
  automation/                 # Scheduled prompt runner + webhook trigger
    scheduler.py              # cron-like loop, job definitions, history
config/
  SOUL.md                     # OpenClaw personality (document analyst)
  AGENTS.md                   # OpenClaw operating rules
  openclaw.config.json5       # OpenClaw config snippet
  jobs.example.json           # sample scheduled jobs
scripts/
  register-openclaw.sh        # idempotent `openclaw mcp set` wrapper
tests/                        # 42 hermetic tests (no net, no creds)
docs/ARCHITECTURE.md
Dockerfile
docker-compose.yml
```

## Runtime flow (matches §4 of the design note)

1. A user messages OpenClaw (via WhatsApp/Telegram/Slack/terminal).
2. OpenClaw reads `SOUL.md` + `AGENTS.md`, picks a model via OpenRouter,
   and discovers the `drive-gateway` MCP server's tools.
3. On a tool call, OpenClaw forwards it to our MCP server.
4. The MCP server validates policy (sandbox, MIME allow-list, byte cap),
   calls Google Drive, logs the call to `audit/mcp-drive.jsonl`, and
   returns the result.
5. OpenClaw loops until the model produces a final answer, then replies
   on the originating channel.

## Security model (summary)

- **Credential isolation.** OpenClaw holds OpenRouter keys. The MCP server
  holds Google credentials. The LLM sees neither.
- **Folder sandbox.** `DriveClient._assert_in_sandbox` walks each file's
  parent chain and refuses anything whose ancestors don't include
  `DRIVE_ROOT_FOLDER_ID`.
- **MIME allow-list.** `DRIVE_ALLOWED_MIME_TYPES` caps readable types.
- **Byte cap.** Reads over `DRIVE_MAX_READ_BYTES` abort mid-download.
- **Audit trail.** Every MCP tool call is appended to
  `audit/mcp-drive.jsonl` with ts, args, status, duration, and error.

See `docs/ARCHITECTURE.md` for the full threat model.

## Tests

```bash
pytest -q
```

All 20 tests are offline (mocked HTTP, in-memory MCP transport, fake Drive)
— no API keys or network required.

## Docker

```bash
docker compose build
docker compose up -d mcp-drive        # daemonise the MCP gateway (prod path)
docker compose up -d web              # web UI at http://localhost:8000
docker compose up -d telegram         # Telegram bot
docker compose up -d scheduler        # automated prompt runner
docker compose run --rm orchestrator chat   # CLI fallback, for dev/demo
```

On a Gandi VPS, run only the `mcp-drive` service, expose the streamable
HTTP transport, and point your OpenClaw config at its public URL (see the
`--remote` branch in `scripts/register-openclaw.sh`).

## A note on how this repo came to be

The first commit mistakenly re-implemented an "OpenClaw-style" orchestrator
from scratch — the author's knowledge cutoff pre-dated OpenClaw's January
2026 launch. The second commit realigns the codebase: OpenClaw is now used
as intended (external orchestrator), and the in-repo Python orchestrator
has been demoted to a fallback runner. The MCP Drive gateway was already
correct in the first pass and is unchanged.
