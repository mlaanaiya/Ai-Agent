# AI Agent — Sovereign, MCP-native autonomous assistant

First stable implementation of the architecture described in the note of
15 April 2026: a document-processing AI agent built around four pillars.

| Pillar | What it does | Where it lives in this repo |
| --- | --- | --- |
| **Orchestrator** (OpenClaw-style) | Runs the agent loop, keeps short-term memory, coordinates tools | `src/orchestrator/` |
| **LLM gateway** (OpenRouter) | Routes each request to the best/cheapest model | `src/orchestrator/openrouter.py` |
| **MCP gateway** (Gandi-hosted) | Exposes Google Drive as audited, sandboxed tools | `src/mcp_drive_server/` |
| **Document store** (Google Drive) | Source of truth for inputs and deliverables | — (external) |

The orchestrator talks to the MCP server via the **Model Context Protocol**
(stdio locally, streamable HTTP in production). The MCP server is the *only*
component that holds Google credentials.

## Why this architecture

- **Zero vendor lock-in**: switch models by changing `OPENROUTER_DEFAULT_MODEL`.
- **Zero-trust data access**: the LLM never sees OAuth tokens; every Drive
  operation goes through the MCP gateway, is sandboxed to a single folder, and
  is audited to a JSONL log.
- **FinOps controls**: `OPENROUTER_MAX_COST_USD` aborts runaway runs.
- **Extensibility**: add a new MCP server (Slack, Notion, a CRM…) and the
  orchestrator picks up its tools automatically at startup.

## Quickstart

### 1. Install

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
```

### 2. Provision Google Drive

1. In Google Cloud, create a **service account** and download its JSON key.
   Save it at `./secrets/service_account.json`.
2. In Drive, **share the target folder** (the "sandbox") with the service
   account's email address. Read/write as needed.
3. Copy the folder ID from its URL into `DRIVE_ROOT_FOLDER_ID`.

### 3. Configure

```bash
cp .env.example .env
# Fill in OPENROUTER_API_KEY and DRIVE_ROOT_FOLDER_ID at minimum.
```

### 4. Use

```bash
# See what MCP tools are available:
ai-agent tools

# One-shot question:
ai-agent ask "Summarise the Q3 meeting notes in the Strategy folder."

# Interactive chat with persistent session memory:
ai-agent chat
```

## Repository layout

```
src/
  orchestrator/         # OpenClaw-style agent
    agent.py            # tool-using loop
    openrouter.py       # OpenRouter client (OpenAI-compatible API)
    mcp_client.py       # wraps an MCP session, exposes OpenAI-format tools
    memory.py           # short-term conversation memory
    cli.py              # typer CLI: ask / chat / tools
    prompts/system.md   # default system prompt
  mcp_drive_server/     # Drive-backed MCP server
    server.py           # FastMCP app + audit hook
    drive.py            # sandboxed Drive wrapper (policy lives here)
    audit.py            # append-only JSONL audit log
    config.py           # pydantic settings
tests/                  # 20 tests, all hermetic (no network / no credentials)
docker-compose.yml
Dockerfile
docs/ARCHITECTURE.md    # deeper design notes, threat model, deployment
```

## Runtime flow (matches the spec's §4)

1. User runs `ai-agent ask "…"` (or sends a message that the orchestrator
   picks up from a queue/webhook).
2. Orchestrator discovers MCP tools via `MCPGateway.connect_*()` and renders
   them as OpenAI tool definitions.
3. It sends the conversation to OpenRouter with the tool list.
4. If the model requests a tool, the orchestrator forwards the call to the
   MCP server, which validates policy (sandbox, MIME, size cap), hits the
   Drive API, records the call in `audit/mcp-drive.jsonl`, and returns the
   result.
5. The tool result is appended to memory and the loop continues until the
   model produces a final answer (or `AGENT_MAX_STEPS` / cost budget hits).

## Security model (summary)

- **Credentials isolation.** The orchestrator has *no* Google credentials. It
  can only invoke whitelisted MCP tools. The MCP server holds the service
  account key and is the only process that touches Drive.
- **Folder sandbox.** `DriveClient._assert_in_sandbox` walks a file's parent
  chain and refuses any file whose ancestor chain does not include
  `DRIVE_ROOT_FOLDER_ID`.
- **MIME allow-list.** `DRIVE_ALLOWED_MIME_TYPES` caps which types can be
  *read*. Defaults to Google Docs, Sheets, plain text, markdown, CSV, PDF.
- **Byte cap.** Reads larger than `DRIVE_MAX_READ_BYTES` abort mid-download.
- **Cost cap.** `OPENROUTER_MAX_COST_USD` stops an agent run when the
  cumulative reported cost exceeds the budget.
- **Audit trail.** Every MCP tool call is written to `audit/mcp-drive.jsonl`
  with timestamp, arguments, status, duration, and error (if any).

See `docs/ARCHITECTURE.md` for a full threat model.

## Running the tests

```bash
pytest -q
```

All tests are offline (mocked HTTP transport, in-memory MCP transport, fake
Drive) — no API keys or network required.

## Docker

```bash
docker compose build
docker compose run --rm orchestrator chat
```

The `mcp-drive` service is structured as a daemon for when you switch to the
HTTP transport (recommended for the Gandi-hosted deployment). For local
development, the orchestrator spawns the MCP server over stdio and this
service can remain stopped.

## Roadmap (post-PoC)

- Streamable HTTP transport for the MCP server (auth with bearer token
  already wired in `MCPGateway.connect_http`).
- Persistent memory backend (SQLite → Postgres).
- Message-bus triggers (Slack, email, cron) feeding `agent.run()`.
- Per-tool rate limits and per-user ACLs on the MCP server.
