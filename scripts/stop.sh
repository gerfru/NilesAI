#!/bin/bash

# Niles AI - Stop Script
# Stoppt alle Docker Services

echo "🛑 Stopping Niles AI..."
echo ""

# Change to Niles root directory
cd "$(dirname "$0")/.."

# Stop Docker services
echo "📦 Stopping Docker containers..."

# Stop containers from current docker-compose.yml
docker compose -f docker/docker-compose.yml --env-file .env stop 2>/dev/null || true

# Also stop old containers (if they exist)
docker stop n8n evolution_api evolution_postgres 2>/dev/null || true

echo "✅ All Niles containers stopped"

echo ""
echo "✅ All services stopped!"
echo ""
echo "💡 To start again: ./scripts/start.sh"
echo "💡 To completely remove (including data): ./scripts/cleanup.sh"
