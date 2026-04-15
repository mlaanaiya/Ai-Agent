#!/usr/bin/env bash
# Register this workspace's drive-gateway MCP server with OpenClaw.
#
# Usage:
#   ./scripts/register-openclaw.sh            # local (stdio) variant
#   ./scripts/register-openclaw.sh --remote   # Gandi-hosted (streamable-http)
#
# Prereqs:
#   * openclaw CLI installed and onboarded (`openclaw onboard --auth-choice openrouter-api-key`)
#   * $DRIVE_ROOT_FOLDER_ID exported in your shell
#   * secrets/service_account.json present for the stdio variant
#
# Idempotent: re-running replaces the server entry.

set -euo pipefail

command -v openclaw >/dev/null || {
    echo "error: openclaw CLI not found. Install it first: https://openclaw.ai" >&2
    exit 1
}

: "${DRIVE_ROOT_FOLDER_ID:?export DRIVE_ROOT_FOLDER_ID first (the sandbox folder id)}"

WORKSPACE="$(cd "$(dirname "$0")/.." && pwd)"
SERVER_NAME="drive-gateway"

if [[ "${1:-}" == "--remote" ]]; then
    : "${MCP_SERVER_URL:?export MCP_SERVER_URL (e.g. https://mcp.example.gandi.net/mcp)}"
    : "${MCP_SERVER_TOKEN:?export MCP_SERVER_TOKEN (bearer token for the remote MCP)}"
    CONFIG_JSON=$(cat <<JSON
{
  "transport": "streamable-http",
  "url": "${MCP_SERVER_URL}",
  "headers": {
    "Authorization": "Bearer ${MCP_SERVER_TOKEN}"
  }
}
JSON
)
else
    CONFIG_JSON=$(cat <<JSON
{
  "command": "python",
  "args": ["-m", "mcp_drive_server"],
  "cwd": "${WORKSPACE}",
  "env": {
    "GOOGLE_SERVICE_ACCOUNT_FILE": "${WORKSPACE}/secrets/service_account.json",
    "DRIVE_ROOT_FOLDER_ID": "${DRIVE_ROOT_FOLDER_ID}",
    "DRIVE_ALLOWED_MIME_TYPES": "application/pdf,application/vnd.google-apps.document,application/vnd.google-apps.spreadsheet,text/plain,text/markdown,text/csv",
    "DRIVE_MAX_READ_BYTES": "2000000",
    "MCP_AUDIT_LOG": "${WORKSPACE}/audit/mcp-drive.jsonl"
  }
}
JSON
)
fi

echo "Registering MCP server '${SERVER_NAME}' with OpenClaw..."
openclaw mcp set "${SERVER_NAME}" "${CONFIG_JSON}"
openclaw mcp show "${SERVER_NAME}"
echo "Done. Verify with: openclaw mcp list"
