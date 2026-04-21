#!/usr/bin/env bash
# Register this workspace's drive-gateway MCP server with OpenClaw.
#
# Usage:
#   ./scripts/register-openclaw.sh            # local (stdio) variant
#   ./scripts/register-openclaw.sh --remote   # Gandi-hosted (streamable-http)
#   ./scripts/register-openclaw.sh --with-enterprise
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
WITH_ENTERPRISE=0
REMOTE=0

for arg in "$@"; do
  if [[ "$arg" == "--with-enterprise" ]]; then
    WITH_ENTERPRISE=1
  elif [[ "$arg" == "--remote" ]]; then
    REMOTE=1
  fi
done

if [[ "${REMOTE}" == "1" ]]; then
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

if [[ "${WITH_ENTERPRISE}" == "1" ]]; then
  ENTERPRISE_NAME="enterprise-gateway"
  ENTERPRISE_JSON=$(cat <<JSON
{
  "command": "python",
  "args": ["-m", "mcp_enterprise_server"],
  "cwd": "${WORKSPACE}",
  "env": {
    "ENTERPRISE_POLICIES_DIR": "${WORKSPACE}/config/enterprise_policies",
    "ENTERPRISE_REQUEST_OUTBOX": "${WORKSPACE}/var/enterprise_requests",
    "ENTERPRISE_AUDIT_LOG": "${WORKSPACE}/audit/mcp-enterprise.jsonl",
    "ENTERPRISE_MAX_POLICY_BYTES": "250000",
    "ENTERPRISE_ALLOWED_REQUEST_TYPES": "access,incident,change"
  }
}
JSON
)
  echo "Registering MCP server '${ENTERPRISE_NAME}' with OpenClaw..."
  openclaw mcp set "${ENTERPRISE_NAME}" "${ENTERPRISE_JSON}"
  openclaw mcp show "${ENTERPRISE_NAME}"
fi

echo "Done. Verify with: openclaw mcp list"
