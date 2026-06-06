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

# Read specific values from .env (don't source — values may contain
# URLs or commas that bash would misinterpret as commands).
EVOLUTION_API_KEY=$(grep -s '^EVOLUTION_API_KEY=' .env | head -1 | cut -d= -f2-)
export EVOLUTION_API_KEY

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

# Check Niles Core (via homelab-gateway)
echo "Niles Core:"
if HEALTH=$(curl -sk https://niles.example.local/health 2>&1); then
    if echo "$HEALTH" | grep -q '"status":"ok"'; then
        echo "  Running on https://niles.example.local"
    else
        echo "  Running but health check failed"
    fi
else
    echo "  Not reachable"
fi

# Check Evolution API (via homelab-gateway)
echo ""
echo "Evolution API:"
if RESPONSE=$(curl -sk https://whatsapp.example.local/ 2>&1); then
    if echo "$RESPONSE" | grep -q "Welcome to the Evolution API"; then
        echo "  Running on https://whatsapp.example.local"

        # Check WhatsApp instance status (instance names are dynamic: niles-wa-{user_id})
        echo ""
        echo "  WhatsApp Instances:"
        if INSTANCES=$(curl -sk -H "apikey: ${EVOLUTION_API_KEY}" https://whatsapp.example.local/instance/fetchInstances 2>&1); then
            INSTANCE_COUNT=$(echo "$INSTANCES" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    if not data:
        print('NONE')
    else:
        for inst in data:
            name = inst.get('name', '?')
            status = inst.get('connectionStatus', 'unknown')
            profile = inst.get('profileName', '')
            label = f'{name}: {status}'
            if profile:
                label += f' ({profile})'
            print(label)
except Exception:
    print('ERROR')
" 2>&1)
            if [ "$INSTANCE_COUNT" = "NONE" ]; then
                echo "    No instances created"
            elif [ "$INSTANCE_COUNT" = "ERROR" ]; then
                echo "    Could not parse response"
            else
                echo "$INSTANCE_COUNT" | while read -r line; do
                    echo "    $line"
                done
            fi
        else
            echo "    API not reachable"
        fi
    else
        echo "  Not responding correctly"
    fi
else
    echo "  Not reachable"
fi

# Check Vikunja (via homelab-gateway)
echo ""
echo "Vikunja:"
if RESPONSE=$(curl -sk https://vikunja.example.local/ 2>&1); then
    echo "  Running on https://vikunja.example.local"
else
    echo "  Not reachable"
fi

# Check Signal API
echo ""
echo "Signal API:"
FEATURE_SIGNAL=$(grep -s '^FEATURE_SIGNAL=' .env | cut -d= -f2- || true)
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
echo "Service URLs (HTTPS via homelab-gateway):"
echo "  - Niles Web UI:         https://niles.example.local/ui/login"
echo "  - Evolution Manager:    https://whatsapp.example.local/manager"
echo "  - Vikunja (Todos):      https://vikunja.example.local"
echo "  - Ollama API:           http://localhost:11434/v1"
