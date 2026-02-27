#!/bin/bash

# Niles AI - Stop Script
# Stoppt alle Docker Services

echo "Stopping Niles AI..."
echo ""

# Change to Niles root directory
cd "$(dirname "$0")/.."

# Stop Docker services
echo "Stopping Docker containers..."

# Stop containers from current docker-compose.yml (all profiles)
COMPOSE_CMD="docker compose -f docker/docker-compose.yml --env-file .env"
if grep -qsE '^FEATURE_SEARCH\s*=\s*"?true"?' .env 2>/dev/null; then
    COMPOSE_CMD="$COMPOSE_CMD --profile search"
fi
$COMPOSE_CMD stop 2>/dev/null || true

echo "All Niles containers stopped."

echo ""
echo "To start again: ./scripts/start.sh"
echo "To completely remove (including data): ./scripts/cleanup.sh"
