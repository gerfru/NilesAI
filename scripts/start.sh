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

# Check that proxy network exists (created by homelab-gateway)
if ! docker network inspect proxy >/dev/null 2>&1; then
    echo "Error: 'proxy' Docker network not found!"
    echo ""
    echo "Start homelab-gateway first:"
    echo "  cd ~/Documents/homelab-gateway && make up"
    echo ""
    exit 1
fi

# Build docker compose command with optional profiles
COMPOSE_CMD="docker compose -f docker/docker-compose.yml --env-file .env"
if grep -qsE '^FEATURE_SEARCH\s*=\s*"?true"?' .env 2>/dev/null; then
    COMPOSE_CMD="$COMPOSE_CMD --profile search"
    echo "Web Search (SearXNG) profile enabled."
    if ! grep -qsE '^SEARXNG_SECRET_KEY\s*=' .env 2>/dev/null; then
        echo "  WARNING: SEARXNG_SECRET_KEY not set in .env — using insecure default."
        echo "  Generate one with: openssl rand -hex 32"
    fi
fi

# Start Docker services
echo "Starting Docker containers..."
$COMPOSE_CMD up -d --build

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
echo "Service URLs (HTTPS via homelab-gateway):"
echo "  - Niles Web UI:      https://niles.example.local/ui/login"
echo "  - Evolution Manager: https://whatsapp.example.local/manager"
echo "  - Vikunja (Todos):   https://vikunja.example.local"
echo "  - Ollama API:        http://localhost:11434/v1"
echo ""

echo "Hint: Ollama must be running externally for chat to work (ollama serve)."
echo "MCP tools (e.g. weather, search) start automatically with Niles Core."
echo ""
echo "Niles AI is ready."
