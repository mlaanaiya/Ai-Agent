# Architecture & Threat Model

## Components

```
  user channels (Web UI / CLI / Scheduler …)
                            |
                            v
                +-------------------------+
                |  OpenClaw Gateway       |  <-- SOUL.md + AGENTS.md
                |  (ReAct loop, memory)   |      drive OpenClaw config
                +-----------+-------------+
                            | (A) OpenAI-compatible tool-calling
                            v
        +-------------------------------------+
        |         build_llm() factory         |
        |  LLM_BACKEND=gemini | ollama        |
        +--------+-----------------+----------+
                 |                 |
                 v                 v
  +--------------------+  +-------------------+
  | Gemini 2.0 Flash   |  |  Ollama (local)   |
  | (free tier, cloud)  |  |  (on-host, free)  |
  +--------------------+  +-------------------+
                 \                /
                  v              v
                +-----------------------+
                |    MCP Drive Gateway  |          audit log (JSONL)
                |    (this repo)        +-------> ./audit/mcp-drive.jsonl
                +-----------+-----------+
                            | Drive API v3
                            v
                +-----------------------+
                |     Google Drive      |
                |   (sandboxed folder)  |
                +-----------------------+
```

Only the **MCP Drive Gateway** box is code owned by this repository. The
Gateway is the real OpenClaw binary, configured via the artifacts in
`config/`.

A fallback runner (`src/orchestrator/`) also exists in this repo and takes
OpenClaw's place when it is not installed — useful for CI and hermetic
demos. The trust model below applies equally to both deployments.

The repository now contains three additional integration layers compared with
the initial Drive-only shape:

- an OpenAI-compatible remote LLM backend (`LLM_BACKEND=openai`)
- a second MCP server, `enterprise-gateway`, for approved internal tools
- a Telegram webhook channel with whitelist by Telegram user/chat identifiers

## Trust boundaries

1. **User / Telegram ↔ Orchestrator.** Treat the user prompt as untrusted. The
   orchestrator does not execute shell commands or eval strings from the
   model — the only effect it has on the outside world is MCP tool calls,
   each of which is declaratively typed. Telegram ingress is gated by
   `TELEGRAM_ALLOWED_USER_IDS` / `TELEGRAM_ALLOWED_CHAT_IDS`, and private
   chats are enforced by default.
2. **Orchestrator ↔ LLM (Gemini / Ollama / OpenAI-compatible).** The LLM is treated as
   adversarial: it may emit malformed tool arguments, try to call tools
   that don't exist, or request files outside the sandbox. All three are
   handled: invalid JSON degrades to `{}` (see `agent.py`); unknown tools
   produce an MCP error that is fed back to the model; out-of-sandbox
   reads raise `DriveError` and are reported to the LLM as a tool error.
   Both backends use the same OpenAI-compatible chat/completions format.
   With Ollama, prompts never leave the host. With Gemini or a remote
   OpenAI-compatible API, prompts leave the host but no Google Drive or
   enterprise backend credentials are exposed.
3. **Orchestrator ↔ MCP server(s).** Over stdio, the trust boundary is the
   process boundary. Over HTTP, use a bearer token (`MCP_SERVER_TOKEN`) and
   TLS. Only the MCP servers hold backend credentials, and the fallback
   runner can aggregate multiple MCP servers while keeping per-tool dispatch
   explicit and auditable.
4. **MCP server ↔ backends.** The Drive gateway uses least privilege via a
   service account explicitly shared only on the sandbox folder. The
   enterprise gateway reads only from `ENTERPRISE_POLICIES_DIR` and writes
   actions only to `ENTERPRISE_REQUEST_OUTBOX`.

## Threats & mitigations

| Threat | Mitigation |
| --- | --- |
| Prompt injection tricks the LLM into exfiltrating files | Sandbox + MIME allow-list + byte cap + audit log. Even a fully-compromised prompt cannot reach files outside `DRIVE_ROOT_FOLDER_ID`. |
| LLM loops on tool calls | `AGENT_MAX_STEPS` hard cap. |
| LLM data exfiltration | Ollama: fully local. Gemini: prompts go to Google API, but no Drive credentials or service-account keys are included. Set `LLM_BACKEND=ollama` for air-gapped operation. |
| Unauthorized Telegram access | Telegram webhook checks shared secret, whitelist by Telegram ID, and private-chat enforcement. |
| OAuth token leak | No OAuth tokens in the orchestrator. Service-account key stays on the MCP host; in Docker it's mounted read-only. |
| Large file exhausts memory | `DRIVE_MAX_READ_BYTES` aborts downloads mid-stream. |
| Path traversal on upload | `save_file` rejects names containing `/`; writes happen via API, not filesystem. |
| Over-exposed internal tools | Enterprise MCP exposes explicit tools only; it is not a generic proxy to arbitrary internal APIs. |
| Audit log tampering | Append-only writes with per-line flush. Ship to a central SIEM in production. |

## Deployment profiles

### Local / dev (stdio transport)

OpenClaw (or the fallback runner) spawns the MCP server as a child process.
Simplest setup, zero network attack surface.

Register with:

```bash
./scripts/register-openclaw.sh --with-enterprise
```

### Gandi-hosted MCP, OpenClaw elsewhere (streamable HTTP transport)

Matches the spec's deployment diagram. The MCP server runs on a Gandi VPS;
OpenClaw runs wherever the user's channels live (laptop, another VPS).

```bash
export MCP_SERVER_URL=https://mcp.example.gandi.net/mcp
export MCP_SERVER_TOKEN=<bearer>
./scripts/register-openclaw.sh --remote
```

### Docker Compose (recommended)

Ollama runs as a container alongside the MCP server and web UI.
Pull the model once, then everything is self-contained:

```bash
docker compose up -d ollama
docker compose exec ollama ollama pull qwen2.5:7b
docker compose up -d
```

## Extensibility

Adding a new MCP server (Slack, Notion, a CRM) means:

1. Spin it up as an independent process/service.
2. Point the orchestrator at it alongside the existing servers through
   `MCP_SERVERS_CONFIG_FILE` (fallback runner) or `openclaw mcp set`
   (OpenClaw-native deployment).
3. The orchestrator discovers the new tools at startup — no code change
   needed in the agent loop.

## Non-goals (this version)

- **Long-term memory / RAG index.** Intentionally out of scope; punt to a
  later iteration with a vector store.
- **Multi-user.** Single-tenant by design; a per-user ACL layer in the MCP
  server is the right place to add this.
