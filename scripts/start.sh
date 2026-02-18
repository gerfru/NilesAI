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
docker compose -f docker/docker-compose.yml --env-file .env up -d

# Wait for services to be ready
echo "Waiting for services to start..."
sleep 10

# Check status
echo ""
echo "Services started."
echo ""
echo "Status:"
docker compose -f docker/docker-compose.yml ps

echo ""
echo "Service URLs (HTTPS via Caddy, self-signed):"
echo "  - Niles Core:        https://localhost"
echo "  - Niles API Docs:    https://localhost/docs"
echo "  - n8n:               https://localhost:5678"
echo "  - Evolution API:     https://localhost:8443"
echo "  - Evolution Manager: https://localhost:8443/manager"
echo ""
echo "Next steps:"
echo "  1. Open LM Studio manually: open -a 'LM Studio'"
echo "  2. Start LM Studio Server (Port 1234)"
echo ""
echo "Niles AI is ready."
