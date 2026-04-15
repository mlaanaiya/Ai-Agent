FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install dependencies first so code changes don't bust the layer cache.
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir .

# Non-root user for runtime safety.
RUN useradd --system --home /app --shell /sbin/nologin aiagent \
    && mkdir -p /app/audit /app/secrets \
    && chown -R aiagent:aiagent /app
USER aiagent

# Default: run the MCP Drive server over stdio. docker-compose overrides for
# the orchestrator service.
CMD ["python", "-m", "mcp_drive_server"]
