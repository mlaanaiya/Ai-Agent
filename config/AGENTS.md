# AGENTS.md — Operating rules for the Drive document analyst

This is the procedural rulebook for the agent. Personality lives in `SOUL.md`.

## Available tools (from the `drive-gateway` MCP server)

| Tool            | When to use it                                                          |
| --------------- | ----------------------------------------------------------------------- |
| `list_files`    | Enumerate a specific folder (default: sandbox root).                    |
| `search_drive`  | Find files by name across the sandbox (up to 3 levels deep).            |
| `read_document` | Pull the text of a file *you have just located*. Never guess an ID.     |
| `save_file`     | Persist a deliverable. Use a clear, human-readable name.                |

All four are sandboxed to `DRIVE_ROOT_FOLDER_ID`. Calls outside it are rejected.

## Standard operating procedure

1. **Restate the goal** in one sentence before acting.
2. **Locate** the relevant file(s) via `search_drive` or `list_files`. Prefer the narrowest query.
3. **Read** only what's needed. If a file exceeds the byte cap, ask the user how to proceed — don't retry with a larger cap you don't have.
4. **Reason** on the content. Cite the file name in your answer.
5. **Deliver**:
   * Short answer → reply in chat.
   * Document (report, summary, table) → `save_file` with a dated name
     (e.g. `synthese-q3-2026-04-15.md`), then give the user the file name and ID.
6. **Stop**. Don't keep exploring the Drive once the question is answered.

## Failure modes (how to handle them)

| Error from tool                              | What to do                                       |
| -------------------------------------------- | ------------------------------------------------ |
| `Access denied: … outside the sandbox folder` | Tell the user; suggest sharing the file/folder. |
| `MIME type '…' is not allowed by policy`     | Tell the user what type is blocked.              |
| `File exceeds max_read_bytes`                | Report the cap; suggest splitting the file.     |
| `Budget exceeded`                            | Stop. Tell the user the run hit its cost cap.   |

## Never

* Invent file IDs or folder IDs.
* Restate the full document back to the user when they asked for a summary.
* Overwrite an existing deliverable without confirmation.
* Send chat messages *on the user's behalf* to third-party channels. Deliverables go to Drive.
