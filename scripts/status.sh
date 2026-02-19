#!/bin/bash

# Niles AI - Status Check Script
# Prueft ob alle Services laufen

set -euo pipefail

# Change to Niles root directory
cd "$(dirname "$0")/.."

# Check prerequisites
if ! command -v docker &>/dev/null; then
    echo "Error: docker not found. Please install Docker Desktop."
    exit 1
fi

# Load environment variables if .env exists
if [ -f .env ]; then
    set -a
    source .env
    set +a
fi

echo "Niles AI - Status Check"
echo ""

# Check Docker
echo "Docker Services:"
docker compose -f docker/docker-compose.yml ps
echo ""

# Check Niles Core (via Caddy HTTPS)
echo "Niles Core:"
if HEALTH=$(curl -sk https://localhost/health 2>&1); then
    if echo "$HEALTH" | grep -q '"status":"ok"'; then
        echo "  Running on https://localhost"
    else
        echo "  Running but health check failed"
    fi
else
    echo "  Not reachable"
fi

# Check Evolution API (via Caddy HTTPS)
echo ""
echo "Evolution API:"
if RESPONSE=$(curl -sk https://localhost:8443/ 2>&1); then
    if echo "$RESPONSE" | grep -q "Welcome to the Evolution API"; then
        echo "  Running on https://localhost:8443"

        # Check WhatsApp instance status
        echo ""
        echo "  WhatsApp Instance:"
        if INSTANCE=$(curl -sk -H "apikey: ${EVOLUTION_API_KEY}" https://localhost:8443/instance/connectionState/niles-whatsapp 2>&1); then
            if echo "$INSTANCE" | grep -q '"state":"open"'; then
                echo "    Connected"
            elif echo "$INSTANCE" | grep -q '"state":"connecting"'; then
                echo "    Connecting (scan QR code)"
            else
                echo "    Disconnected"
            fi
        else
            echo "    Not created yet"
        fi
    else
        echo "  Not responding correctly"
    fi
else
    echo "  Not reachable"
fi

# Check LM Studio (simple port check)
echo ""
echo "LM Studio:"
if nc -z localhost 1234 2>/dev/null; then
    echo "  Server running on http://localhost:1234"
else
    echo "  Server not running (start manually in LM Studio)"
fi

echo ""
echo "Service URLs (HTTPS via Caddy, self-signed):"
echo "  - Niles Web UI:         https://localhost/ui/chat"
echo "  - Niles API Docs:       https://localhost/docs"
echo "  - Evolution Manager:    https://localhost:8443/manager"
echo "  - LM Studio API:        http://localhost:1234/v1"
