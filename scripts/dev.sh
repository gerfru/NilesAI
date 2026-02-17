#!/bin/bash

# Niles AI - Development Server
# Startet den Niles Core lokal (ohne Docker) mit Auto-Reload

set -e

# Change to Niles root directory
cd "$(dirname "$0")/.."

echo "🛠️  Starting Niles Core (Development Mode)..."
echo ""

# Check if .venv exists
if [ ! -d .venv ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv .venv
    echo ""
fi

# Activate venv
source .venv/bin/activate

# Check if dependencies are installed
if ! python -c "import niles" 2>/dev/null; then
    echo "📦 Installing dependencies..."
    pip install -e ".[dev]" --quiet
    echo ""
fi

echo "🚀 Starting uvicorn with auto-reload..."
echo "   http://localhost:8000"
echo "   http://localhost:8000/docs (OpenAPI)"
echo "   http://localhost:8000/health"
echo ""
echo "   Press Ctrl+C to stop"
echo ""

uvicorn niles.main:app --host 127.0.0.1 --port 8000 --reload
