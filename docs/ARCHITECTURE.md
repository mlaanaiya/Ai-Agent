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

## Trust boundaries

1. **User ↔ Orchestrator.** Treat the user prompt as untrusted. The
   orchestrator does not execute shell commands or eval strings from the
   model — the only effect it has on the outside world is MCP tool calls,
   each of which is declaratively typed.
2. **Orchestrator ↔ LLM (Gemini / Ollama).** The LLM is treated as
   adversarial: it may emit malformed tool arguments, try to call tools
   that don't exist, or request files outside the sandbox. All three are
   handled: invalid JSON degrades to `{}` (see `agent.py`); unknown tools
   produce an MCP error that is fed back to the model; out-of-sandbox
   reads raise `DriveError` and are reported to the LLM as a tool error.
   Both backends use the same OpenAI-compatible chat/completions format.
   With Ollama, prompts never leave the host. With Gemini, prompts go to
   Google's API but no Google Drive credentials are exposed.
3. **Orchestrator ↔ MCP server.** Over stdio, the trust boundary is the
   process boundary. Over HTTP, use a bearer token (`MCP_SERVER_TOKEN`) and
   TLS. Only the MCP server holds Google credentials.
4. **MCP server ↔ Google Drive.** Least privilege via service account that
   is explicitly shared only on the sandbox folder.

## Threats & mitigations

| Threat | Mitigation |
| --- | --- |
| Prompt injection tricks the LLM into exfiltrating files | Sandbox + MIME allow-list + byte cap + audit log. Even a fully-compromised prompt cannot reach files outside `DRIVE_ROOT_FOLDER_ID`. |
| LLM loops on tool calls | `AGENT_MAX_STEPS` hard cap. |
| LLM data exfiltration | Ollama: fully local. Gemini: prompts go to Google API, but no Drive credentials or service-account keys are included. Set `LLM_BACKEND=ollama` for air-gapped operation. |
| OAuth token leak | No OAuth tokens in the orchestrator. Service-account key stays on the MCP host; in Docker it's mounted read-only. |
| Large file exhausts memory | `DRIVE_MAX_READ_BYTES` aborts downloads mid-stream. |
| Path traversal on upload | `save_file` rejects names containing `/`; writes happen via API, not filesystem. |
| Audit log tampering | Append-only writes with per-line flush. Ship to a central SIEM in production. |

## Deployment profiles

### Local / dev (stdio transport)

OpenClaw (or the fallback runner) spawns the MCP server as a child process.
Simplest setup, zero network attack surface.

Register with:

```bash
./scripts/register-openclaw.sh
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
2. Point the orchestrator at it (either alongside the Drive server or
   instead of it; multi-server support is a near-term roadmap item).
3. The orchestrator discovers the new tools at startup — no code change
   needed in the agent loop.

## Non-goals (this version)

- **Long-term memory / RAG index.** Intentionally out of scope; punt to a
  later iteration with a vector store.
- **Multi-user.** Single-tenant by design; a per-user ACL layer in the MCP
  server is the right place to add this.
