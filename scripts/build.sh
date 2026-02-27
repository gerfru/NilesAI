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

# Extract version from pyproject.toml
VERSION=$(python3 -c "
import tomllib
print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])
" 2>/dev/null || echo "dev")

export NILES_VERSION="$VERSION"
echo "Building Niles AI v${VERSION}..."

COMPOSE_CMD="docker compose -f docker/docker-compose.yml --env-file .env"
if grep -qsE '^FEATURE_SEARCH\s*=\s*"?true"?' .env 2>/dev/null; then
    COMPOSE_CMD="$COMPOSE_CMD --profile search"
    echo "Web Search (SearXNG) profile included."
fi

if [ "${1:-}" = "--clean" ]; then
    echo "Clean rebuild (no cache)..."
    $COMPOSE_CMD build --no-cache
else
    $COMPOSE_CMD build
fi

echo ""
echo "Build complete: niles-core:${VERSION}"
echo "Run ./scripts/start.sh to start."
