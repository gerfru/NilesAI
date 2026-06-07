#!/bin/bash

# Niles AI — Integration Test Runner
# Runs integration tests against real Docker Compose infrastructure.
# Prerequisites: Docker Compose running, Ollama running, .env configured.

set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
    echo "Error: .env file not found. Integration tests need real credentials."
    exit 1
fi

# Load .env for DB credentials, API keys etc.
# Cannot use `source .env` because values may contain unquoted special chars
# (URLs with commas, etc.) that bash interprets as commands.
while IFS='=' read -r key value; do
    # Skip comments and empty lines
    [[ -z "$key" || "$key" =~ ^[[:space:]]*# ]] && continue
    # Strip leading/trailing whitespace from key
    key="${key// /}"
    # Export the variable
    export "$key"="$value"
done < .env

# Host addresses for local execution (outside Docker network)
export POSTGRES_HOST="${POSTGRES_HOST:-127.0.0.1}"
export POSTGRES_HOST_PORT="${POSTGRES_HOST_PORT:-5432}"
export POSTGRES_DB="${POSTGRES_DB:-evolution_db}"
export POSTGRES_USER="${POSTGRES_USER:-evolution}"
# Docker-internal URLs are not reachable from the host.
# Rewrite to homelab-gateway (HTTPS via subdomains).
# Evolution API: http://evolution_api:8080 → https://whatsapp.home.lab
if [[ "${EVOLUTION_API_URL:-}" == *"evolution"* ]]; then
    export EVOLUTION_API_URL="https://whatsapp.home.lab"
fi
export EVOLUTION_API_URL="${EVOLUTION_API_URL:-https://whatsapp.home.lab}"

# Vikunja: http://vikunja:3456 → https://vikunja.home.lab/api/v1
if [[ "${VIKUNJA_API_URL:-}" == *"vikunja:"* ]]; then
    export VIKUNJA_API_URL="https://vikunja.home.lab/api/v1"
fi

# Signal API: only reachable inside Docker network (no Caddy route).
# Expose via docker-compose port mapping if needed for local testing.
if [[ "${SIGNAL_API_URL:-}" == *"signal_api:"* ]]; then
    export SIGNAL_API_URL="http://localhost:18080"
fi

# SearXNG: only reachable inside Docker network (no Caddy route).
if [[ "${SEARXNG_URL:-}" == *"searxng:"* ]]; then
    export SEARXNG_URL="http://localhost:18888"
fi

# Activate venv (needed before Python-based token fetch)
if [ ! -d .venv ]; then
    echo "Creating virtual environment..."
    "${PYTHON:-python3.14}" -m venv .venv
fi
source .venv/bin/activate

if ! python -c "import pytest" 2>/dev/null; then
    echo "Installing dependencies..."
    python -m pip install --upgrade pip --quiet
    python -m pip install -e ".[dev]" --quiet
fi

# Auto-fetch Vikunja API token from DB if not already set.
# Credentials are passed via env vars to avoid shell injection from special
# characters in passwords (e.g. single quotes).
if [ -z "${VIKUNJA_API_TOKEN:-}" ]; then
    VIKUNJA_API_TOKEN=$(PGHOST="$POSTGRES_HOST" PGPORT="$POSTGRES_HOST_PORT" \
        PGDB="$POSTGRES_DB" PGUSER="$POSTGRES_USER" \
        PGPASSWORD="$EVOLUTION_POSTGRES_PASSWORD" \
        python3 -c "
import asyncio, asyncpg, os
async def q():
    try:
        c = await asyncpg.connect(
            host=os.environ['PGHOST'], port=int(os.environ['PGPORT']),
            database=os.environ['PGDB'], user=os.environ['PGUSER'],
            password=os.environ['PGPASSWORD'], timeout=3)
        v = await c.fetchval('SELECT api_token FROM vikunja_credentials LIMIT 1')
        await c.close()
        print(v or '', end='')
    except Exception:
        pass
asyncio.run(q())
" 2>/dev/null || true)
    if [ -n "$VIKUNJA_API_TOKEN" ]; then
        export VIKUNJA_API_TOKEN
        echo " Vikunja token: auto-fetched from DB"
    else
        echo " Vikunja token: not found — Vikunja tests will be skipped"
    fi
fi

echo "============================================"
echo " Niles Integration Tests"
echo "============================================"
echo ""
echo " PostgreSQL: $POSTGRES_HOST:$POSTGRES_HOST_PORT"
echo " Evolution:  ${EVOLUTION_API_URL:-not set}"
echo " Vikunja:    ${VIKUNJA_API_URL:-not set}"
echo " Signal:     ${SIGNAL_API_URL:-not set}"
echo " SearXNG:    ${SEARXNG_URL:-not set}"
echo " Ollama:     ${LLM_BASE_URL:-http://127.0.0.1:11434/v1}"
echo ""

python -m pytest tests/integration/ -v -m integration "$@"
