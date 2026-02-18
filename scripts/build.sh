#!/bin/bash

# Niles AI - Build Script
# Rebuilds alle Docker Images (ohne Cache bei --clean)

set -euo pipefail

cd "$(dirname "$0")/.."

if ! command -v docker &>/dev/null; then
    echo "Error: docker not found. Please install Docker Desktop."
    exit 1
fi

if ! docker info &>/dev/null; then
    echo "Error: Docker daemon is not running. Please start Docker Desktop."
    exit 1
fi

if [ "${1:-}" = "--clean" ]; then
    echo "Clean rebuild (no cache)..."
    docker compose -f docker/docker-compose.yml --env-file .env build --no-cache
else
    echo "Building Niles AI images..."
    docker compose -f docker/docker-compose.yml --env-file .env build
fi

echo ""
echo "Build complete. Run ./scripts/start.sh to start."
