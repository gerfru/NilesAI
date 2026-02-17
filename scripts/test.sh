#!/bin/bash

# Niles AI - Test Runner
# Führt alle pytest Tests aus

set -e

# Change to Niles root directory
cd "$(dirname "$0")/.."

echo "🧪 Running Niles Tests..."
echo ""

# Check if .venv exists
if [ ! -d .venv ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv .venv
fi

# Activate venv
source .venv/bin/activate

# Check if dependencies are installed
if ! python -c "import pytest" 2>/dev/null; then
    echo "📦 Installing dependencies..."
    pip install -e ".[dev]" --quiet
    echo ""
fi

# Run tests
python -m pytest tests/ -v "$@"
