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
COMPOSE_CMD="docker compose -f docker/docker-compose.yml --env-file .env"
if grep -qsE '^FEATURE_SEARCH\s*=\s*"?true"?' .env 2>/dev/null; then
    COMPOSE_CMD="$COMPOSE_CMD --profile search"
fi
$COMPOSE_CMD ps
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

# Check Vikunja (via Caddy HTTPS)
echo ""
echo "Vikunja:"
if RESPONSE=$(curl -sk https://localhost:3457/ 2>&1); then
    echo "  Running on https://localhost:3457"
else
    echo "  Not reachable"
fi

# Check Signal API
echo ""
echo "Signal API:"
FEATURE_SIGNAL=$(grep -s '^FEATURE_SIGNAL=' .env | cut -d= -f2-)
if [ "${FEATURE_SIGNAL:-}" = "true" ]; then
    if RESPONSE=$(curl -s http://localhost:8080/v1/about 2>&1); then
        echo "  Running"
    else
        # Signal API is internal only (no port exposed), check via Docker
        if docker exec niles_signal_api curl -s http://localhost:8080/v1/about >/dev/null 2>&1; then
            echo "  Running (internal network only)"
        else
            echo "  Not reachable"
        fi
    fi
else
    echo "  Disabled (FEATURE_SIGNAL=false)"
fi

# Check Ollama (simple port check)
echo ""
echo "Ollama:"
if curl -s http://localhost:11434/ >/dev/null 2>&1; then
    echo "  Server running on http://localhost:11434"
else
    echo "  Server not running (start with: ollama serve)"
fi

echo ""
echo "Service URLs (HTTPS via Caddy, self-signed):"
echo "  - Niles Web UI:         https://localhost/ui/login"
echo "  - Evolution Manager:    https://localhost:8443/manager"
echo "  - Vikunja (Todos):      https://localhost:3457"
echo "  - Ollama API:           http://localhost:11434/v1"
