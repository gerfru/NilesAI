#!/bin/bash

# Niles AI - Cleanup Script
# ACHTUNG: Löscht alle Daten und Container!

set -e

# Change to Niles root directory
cd "$(dirname "$0")/.."

echo "⚠️  WARNING: This will delete ALL Niles data!"
echo ""
echo "This includes:"
echo "  - All Docker containers"
echo "  - All Docker volumes (PostgreSQL data)"
echo ""
echo "Will be KEPT as backup:"
echo "  - n8n workflows & credentials (~/.n8n)"
echo "  - WhatsApp sessions (~/.evolution)"
echo ""
read -p "Are you sure? Type 'yes' to continue: " -r
echo ""

if [[ ! $REPLY =~ ^yes$ ]]; then
    echo "❌ Cleanup cancelled"
    exit 1
fi

echo "🗑️  Stopping and removing containers..."

# Remove containers from current docker-compose.yml
docker compose -f docker/docker-compose.yml --env-file .env down -v 2>/dev/null || true

# Also remove old containers (if they exist)
echo "🗑️  Removing old containers..."
docker stop n8n evolution_api evolution_postgres 2>/dev/null || true
docker rm n8n evolution_api evolution_postgres 2>/dev/null || true

echo "📦 Keeping user data..."
if [ -d ~/.n8n ]; then
    echo "    ✅ ~/.n8n (n8n workflows & credentials)"
fi
if [ -d ~/.evolution ]; then
    echo "    ✅ ~/.evolution (WhatsApp sessions)"
fi
echo ""
echo "💡 To delete manually:"
echo "    rm -rf ~/.n8n ~/.evolution"

echo ""
echo "✅ Cleanup complete!"
echo ""
echo "💡 To start fresh:"
echo "   ./scripts/setup-interactive.sh"
