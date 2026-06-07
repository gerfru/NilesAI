#!/bin/bash

# Niles AI - Test Runner
# Führt alle pytest Tests aus

set -euo pipefail

# Change to Niles root directory
cd "$(dirname "$0")/.."

# Check prerequisites
PYTHON="${PYTHON:-python3.14}"
if ! command -v "$PYTHON" &>/dev/null; then
    echo "Error: $PYTHON not found. Please install Python 3.14+."
    exit 1
fi

echo "Running Niles Tests..."
echo ""

# Check if .venv exists
if [ ! -d .venv ]; then
    echo "Creating virtual environment..."
    "$PYTHON" -m venv .venv
fi

# Activate venv
source .venv/bin/activate

# Check if dependencies are installed
if ! python -c "import pytest" 2>/dev/null; then
    echo "Installing dependencies..."
    python -m pip install --upgrade pip --quiet
    python -m pip install -e ".[dev]" --quiet
    echo ""
fi

# Run tests (exclude integration + e2e tests — use dedicated scripts for those)
python -m pytest tests/ -v -m "not integration and not e2e and not llm_judge" "$@"
