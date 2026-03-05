#!/bin/bash

# Niles AI — E2E Test Runner
# Runs end-to-end pipeline tests with FakeLLM or Claude-as-Judge tests.
#
# Usage:
#   ./scripts/test-e2e.sh              # Run FakeLLM pipeline + HTTP tests
#   ./scripts/test-e2e.sh pipeline     # Run FakeLLM pipeline + HTTP tests
#   ./scripts/test-e2e.sh judge        # Run Claude-as-Judge tests (needs ANTHROPIC_API_KEY)
#   ./scripts/test-e2e.sh all          # Run all E2E tests

set -euo pipefail
cd "$(dirname "$0")/.."

# Load .env for DB credentials
if [ -f .env ]; then
    set -a; source .env; set +a
fi

# Host addresses for local execution
export POSTGRES_HOST="${POSTGRES_HOST:-127.0.0.1}"
export POSTGRES_HOST_PORT="${POSTGRES_HOST_PORT:-5432}"
export POSTGRES_USER="${POSTGRES_USER:-evolution}"
export POSTGRES_DB="${POSTGRES_DB:-evolution_db}"

# Activate venv
if [ ! -d .venv ]; then
    echo "Error: .venv not found. Run 'uv venv && uv pip install -e .[dev]' first."
    exit 1
fi
source .venv/bin/activate

if ! python -c "import pytest" 2>/dev/null; then
    echo "Installing dependencies..."
    uv pip install -e ".[dev]" --quiet
fi

MODE="${1:-pipeline}"

echo "Niles E2E Tests"
echo "==============="
echo "  PostgreSQL: $POSTGRES_HOST:$POSTGRES_HOST_PORT"
echo "  Mode:       $MODE"
echo ""

case "$MODE" in
    pipeline)
        echo "Running FakeLLM pipeline + HTTP tests..."
        python -m pytest tests/e2e/ -v -m "e2e and not llm_judge" "${@:2}"
        ;;
    judge)
        if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
            echo "Error: ANTHROPIC_API_KEY not set"
            echo "Export ANTHROPIC_API_KEY before running judge tests."
            exit 1
        fi
        echo "Running Claude-as-Judge tests..."
        echo "  Ollama:     ${LLM_BASE_URL:-http://127.0.0.1:11434/v1}"
        echo "  Claude:     API key set"
        echo ""
        python -m pytest tests/e2e/ -v -m "llm_judge" "${@:2}"
        ;;
    all)
        echo "Running all E2E tests..."
        python -m pytest tests/e2e/ -v "${@:2}"
        ;;
    *)
        echo "Usage: $0 [pipeline|judge|all]"
        echo ""
        echo "Modes:"
        echo "  pipeline   FakeLLM pipeline + HTTP tests (default, needs PostgreSQL)"
        echo "  judge      Claude-as-Judge tests (needs Ollama + ANTHROPIC_API_KEY)"
        echo "  all        All E2E tests"
        exit 1
        ;;
esac
