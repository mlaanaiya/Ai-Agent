# Architecture & Threat Model

## Components

```
                +-----------------------+
  user input -->|    Orchestrator       |
                | (OpenClaw-style loop) |
                +-----------+-----------+
                            | (A) OpenAI-compatible tool-calling
                            v
                +-----------------------+
                |  OpenRouter (LLM)     |
                +-----------------------+
                            ^
                            |   (B) tool calls come back as function_call deltas
                            |
                            v
                +-----------------------+
                |    MCP Gateway        |          audit log (JSONL)
                |  (Drive-backed tools) +-------> ./audit/mcp-drive.jsonl
                +-----------+-----------+
                            | Drive API v3
                            v
                +-----------------------+
                |     Google Drive      |
                |   (sandboxed folder)  |
                +-----------------------+
```

## Trust boundaries

1. **User ↔ Orchestrator.** Treat the user prompt as untrusted. The
   orchestrator does not execute shell commands or eval strings from the
   model — the only effect it has on the outside world is MCP tool calls,
   each of which is declaratively typed.
2. **Orchestrator ↔ LLM (OpenRouter).** The LLM is treated as adversarial:
   it may emit malformed tool arguments, try to call tools that don't exist,
   or request files outside the sandbox. All three are handled:
   invalid JSON degrades to `{}` (see `agent.py`); unknown tools produce an
   MCP error that is fed back to the model; out-of-sandbox reads raise
   `DriveError` and are reported to the LLM as a tool error.
3. **Orchestrator ↔ MCP server.** Over stdio, the trust boundary is the
   process boundary. Over HTTP, use a bearer token (`MCP_SERVER_TOKEN`) and
   TLS. Only the MCP server holds Google credentials.
4. **MCP server ↔ Google Drive.** Least privilege via service account that
   is explicitly shared only on the sandbox folder.

## Threats & mitigations

| Threat | Mitigation |
| --- | --- |
| Prompt injection tricks the LLM into exfiltrating files | Sandbox + MIME allow-list + byte cap + audit log. Even a fully-compromised prompt cannot reach files outside `DRIVE_ROOT_FOLDER_ID`. |
| LLM loops on tool calls | `AGENT_MAX_STEPS` and `OPENROUTER_MAX_COST_USD`. |
| OAuth token leak | No OAuth tokens in the orchestrator. Service-account key stays on the MCP host; in Docker it's mounted read-only. |
| Large file exhausts memory | `DRIVE_MAX_READ_BYTES` aborts downloads mid-stream. |
| Path traversal on upload | `save_file` rejects names containing `/`; writes happen via API, not filesystem. |
| Audit log tampering | Append-only writes with per-line flush. Ship to a central SIEM in production. |

## Deployment profiles

### Local / dev (stdio transport)

The orchestrator spawns the MCP server as a child process. Simplest setup,
zero network attack surface.

```
MCP_TRANSPORT=stdio
```

### Gandi-hosted MCP, orchestrator elsewhere (HTTP transport)

Matches the spec's deployment diagram. The MCP server runs on a Gandi VPS;
the orchestrator can run anywhere (laptop, Gandi Simple Hosting, a cron VM).

```
MCP_TRANSPORT=http
MCP_SERVER_URL=https://mcp.example.gandi.net/mcp
MCP_SERVER_TOKEN=<bearer>
```

The server-side streamable HTTP transport is not wired by default in this
first version — `python -m mcp_drive_server` runs stdio. To expose it over
HTTP, swap the `app.run()` call for the FastMCP HTTP entry point in
`src/mcp_drive_server/__main__.py`. Gandi's Simple Hosting or a Docker
container on a VPS both work.

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
- **Automatic model selection.** We route to `OPENROUTER_DEFAULT_MODEL` for
  now. Dynamic routing (cheap model for search, strong model for synthesis)
  is straightforward to add on top of `OpenRouterClient.chat(model=...)`.
