#!/bin/bash

# Niles AI - Cleanup Script
# ACHTUNG: Loescht alle Daten und Container!

set -e

# Change to Niles root directory
cd "$(dirname "$0")/.."

echo "WARNING: This will delete ALL Niles data!"
echo ""
echo "This includes:"
echo "  - All Docker containers"
echo "  - All Docker volumes (PostgreSQL data)"
echo ""
echo "Will be KEPT as backup:"
echo "  - WhatsApp sessions (~/.evolution)"
echo ""
read -p "Are you sure? Type 'yes' to continue: " -r
echo ""

if [[ ! $REPLY =~ ^yes$ ]]; then
    echo "Cleanup cancelled."
    exit 1
fi

echo "Stopping and removing containers..."

# Remove containers from current docker-compose.yml
docker compose -f docker/docker-compose.yml --env-file .env down -v 2>/dev/null || true

echo "Keeping user data..."
if [ -d ~/.evolution ]; then
    echo "    ~/.evolution (WhatsApp sessions)"
fi
echo ""
echo "To delete manually:"
echo "    rm -rf ~/.evolution"

echo ""
echo "Cleanup complete."
echo ""
echo "To start fresh:"
echo "   cp .env.example .env  # configure secrets"
echo "   ./scripts/build.sh"
echo "   ./scripts/start.sh"
