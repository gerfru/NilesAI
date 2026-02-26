#!/bin/bash

# Niles AI - Start Script
# Startet alle Docker Services

set -euo pipefail

# Change to Niles root directory
cd "$(dirname "$0")/.."

# Check prerequisites
if ! command -v docker &>/dev/null; then
    echo "Error: docker not found. Please install Docker Desktop."
    exit 1
fi

if ! docker info &>/dev/null; then
    echo "Error: Docker daemon is not running. Please start Docker Desktop."
    exit 1
fi

echo "Starting Niles AI..."
echo ""

# Check if .env exists
if [ ! -f .env ]; then
    echo "Error: .env file not found!"
    echo ""
    echo "Please create .env from template:"
    echo "  cp .env.example .env"
    echo "  nano .env"
    echo ""
    exit 1
fi

# Start Docker services
echo "Starting Docker containers..."
docker compose -f docker/docker-compose.yml --env-file .env up -d --build

# Wait for services to be ready
echo "Waiting for services to start..."
sleep 10

# Ensure Vikunja database exists (idempotent, fails silently if already present)
docker exec niles_evolution_postgres createdb -U evolution vikunja_db 2>/dev/null && \
    echo "Created vikunja_db database." || true

# Check status
echo ""
echo "Services started."
echo ""
echo "Status:"
docker compose -f docker/docker-compose.yml ps

echo ""
echo "Service URLs (HTTPS via Caddy, self-signed):"
echo "  - Niles Web UI:      https://localhost/ui/login"
echo "  - Evolution Manager: https://localhost:8443/manager"
echo "  - Vikunja (Todos):   https://localhost:3457"
echo "  - Ollama API:        http://localhost:11434/v1"
echo ""

# Vikunja setup hint (first-time only)
VIKUNJA_TOKEN=$(grep -s '^VIKUNJA_API_TOKEN=' .env | cut -d= -f2-)
FEATURE_VIKUNJA=$(grep -s '^FEATURE_VIKUNJA=' .env | cut -d= -f2-)
if [ "${FEATURE_VIKUNJA:-}" = "true" ] && [ -z "${VIKUNJA_TOKEN:-}" ]; then
    echo "Note: FEATURE_VIKUNJA=true but VIKUNJA_API_TOKEN is not set."
    echo "  1. Open https://localhost:3457 and create an admin account"
    echo "  2. Go to Settings > API Tokens > Create Token"
    echo "  3. Add token to .env as VIKUNJA_API_TOKEN"
    echo "  4. Restart: ./scripts/start.sh"
    echo ""
fi

echo "Hint: Ollama must be running externally for chat to work (ollama serve)."
echo "MCP tools (e.g. weather) start automatically with Niles Core."
echo ""
echo "Niles AI is ready."
