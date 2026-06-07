#!/bin/bash

# Niles AI - Development Server
# Startet den Niles Core lokal (ohne Docker) mit Auto-Reload

set -euo pipefail

# Change to Niles root directory
cd "$(dirname "$0")/.."

# Check prerequisites
PYTHON="${PYTHON:-python3.14}"
if ! command -v "$PYTHON" &>/dev/null; then
    echo "Error: $PYTHON not found. Please install Python 3.14+."
    exit 1
fi

if [ ! -f .env ]; then
    echo "Error: .env file not found!"
    echo "  cp .env.example .env && nano .env"
    exit 1
fi

echo "Starting Niles Core (Development Mode)..."
echo ""

# Check if .venv exists
if [ ! -d .venv ]; then
    echo "Creating virtual environment..."
    "$PYTHON" -m venv .venv
    echo ""
fi

# Activate venv
source .venv/bin/activate

# Check if dependencies are installed
if ! python -c "import niles" 2>/dev/null; then
    echo "Installing dependencies..."
    python -m pip install --upgrade pip --quiet
    python -m pip install -e ".[dev]" --quiet
    echo ""
fi

echo "Starting uvicorn with auto-reload..."
echo "   http://localhost:8000"
echo "   http://localhost:8000/ui/login (Web UI)"
echo "   http://localhost:8000/health"
echo ""
echo "   Press Ctrl+C to stop"
echo ""

uvicorn niles.main:app --host 127.0.0.1 --port 8000 --reload
