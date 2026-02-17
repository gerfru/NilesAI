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

# Check Niles Core
echo "Niles Core:"
if HEALTH=$(curl -s http://localhost:8000/health 2>&1); then
    if echo "$HEALTH" | grep -q '"status":"ok"'; then
        echo "  Running on http://localhost:8000"
    else
        echo "  Running but health check failed"
    fi
else
    echo "  Not reachable"
fi

# Check n8n
echo ""
echo "n8n:"
if curl -s http://localhost:5678 > /dev/null 2>&1; then
    echo "  Running on http://localhost:5678"
else
    echo "  Not reachable"
fi

# Check Evolution API
echo ""
echo "Evolution API:"
if RESPONSE=$(curl -s http://localhost:8080/ 2>&1); then
    if echo "$RESPONSE" | grep -q "Welcome to the Evolution API"; then
        echo "  Running on http://localhost:8080"

        # Check WhatsApp instance status
        echo ""
        echo "  WhatsApp Instance:"
        if INSTANCE=$(curl -s -H "apikey: ${EVOLUTION_API_KEY}" http://localhost:8080/instance/connectionState/niles-whatsapp 2>&1); then
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
echo "Service URLs:"
echo "  - Niles Core:          http://localhost:8000"
echo "  - Niles API Docs:      http://localhost:8000/docs"
echo "  - n8n:                 http://localhost:5678"
echo "  - Evolution Manager:   http://localhost:8080/manager"
echo "  - LM Studio API:       http://localhost:1234/v1"
