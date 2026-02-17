#!/bin/bash

# Niles AI - Test Runner
# Führt alle pytest Tests aus

set -euo pipefail

# Change to Niles root directory
cd "$(dirname "$0")/.."

# Check prerequisites
if ! command -v python3 &>/dev/null; then
    echo "❌ Error: python3 not found. Please install Python 3.11+."
    exit 1
fi

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
