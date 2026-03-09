#!/bin/bash

# Niles AI — LLM Model Benchmark
# Vergleicht Tool-Calling-Qualitaet verschiedener Ollama-Modelle
# mittels Claude-as-Judge Bewertung.
#
# Usage:
#   ./scripts/benchmark-llm.sh                          # Default-Modelle
#   ./scripts/benchmark-llm.sh llama3.1:8b qwen3:8b     # Bestimmte Modelle
#
# Voraussetzungen:
#   - Ollama laeuft lokal
#   - PostgreSQL mit Migrations
#   - ANTHROPIC_API_KEY gesetzt
#   - .env Datei vorhanden

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

# Check ANTHROPIC_API_KEY
if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
    echo "Error: ANTHROPIC_API_KEY not set"
    echo "Export ANTHROPIC_API_KEY before running the benchmark."
    exit 1
fi

# Default models (overridable via CLI args)
if [ $# -eq 0 ]; then
    MODELS=("llama3.1:8b" "llama3.3:latest" "qwen3:8b" "mistral:latest")
else
    MODELS=("$@")
fi

SCORE_DIR=$(mktemp -d)
OLLAMA_URL="${LLM_BASE_URL:-http://127.0.0.1:11434/v1}"
OLLAMA_BASE="${OLLAMA_URL%/v1}"

echo "Niles LLM Benchmark"
echo "==================="
echo "  Ollama:     $OLLAMA_BASE"
echo "  PostgreSQL: $POSTGRES_HOST:$POSTGRES_HOST_PORT"
echo "  Models:     ${MODELS[*]}"
echo "  Claude:     API key set"
echo ""

# Check Ollama reachability
if ! curl -sf "$OLLAMA_BASE/api/tags" >/dev/null 2>&1; then
    echo "Error: Ollama not reachable at $OLLAMA_BASE"
    exit 1
fi

# Run benchmark for each model
for MODEL in "${MODELS[@]}"; do
    echo "---------------------------------------"
    echo "Model: $MODEL"
    echo "---------------------------------------"

    # Pull model if not available
    echo "  Pulling model (if needed)..."
    ollama pull "$MODEL" 2>&1 | tail -1

    # Sanitize model name for filename
    MODEL_SAFE=$(echo "$MODEL" | tr ':/' '__')
    SCORE_FILE="$SCORE_DIR/scores_${MODEL_SAFE}.json"

    echo "  Running judge tests..."
    LLM_MODEL="$MODEL" SCORE_OUTPUT="$SCORE_FILE" \
        python -m pytest tests/e2e/test_llm_judge.py -v -m "llm_judge" \
        --tb=short 2>&1 | while IFS= read -r line; do echo "    $line"; done || true

    echo ""
done

echo ""
echo "======================================="
echo "Results"
echo "======================================="
echo ""

# Parse and display results table
python3 - "$SCORE_DIR" "${MODELS[@]}" <<'PYEOF'
import json
import sys
from pathlib import Path

score_dir = Path(sys.argv[1])
models = sys.argv[2:]

criteria = [
    "tool_selection",
    "tool_arguments",
    "response_quality",
    "personality",
    "language",
]

headers = ["Model", "Tool Sel.", "Tool Args", "Response", "Personality", "Language", "Avg"]
widths = [20, 10, 10, 10, 12, 10, 6]

# Header
header_line = " | ".join(h.ljust(w) for h, w in zip(headers, widths))
sep_line = "-|-".join("-" * w for w in widths)
print(f"| {header_line} |")
print(f"|-{sep_line}-|")

for model in models:
    model_safe = model.replace(":", "__").replace("/", "__")
    score_file = score_dir / f"scores_{model_safe}.json"

    if not score_file.exists():
        row = " | ".join(
            [model.ljust(widths[0])] + ["n/a".ljust(w) for w in widths[1:]]
        )
        print(f"| {row} |")
        continue

    data = json.loads(score_file.read_text())
    if not data:
        row = " | ".join(
            [model.ljust(widths[0])] + ["n/a".ljust(w) for w in widths[1:]]
        )
        print(f"| {row} |")
        continue

    # Average scores per criterion
    avgs = {}
    for c in criteria:
        vals = [d["scores"].get(c, 0) for d in data if c in d.get("scores", {})]
        avgs[c] = sum(vals) / len(vals) if vals else 0.0

    overall = sum(avgs.values()) / len(avgs) if avgs else 0.0

    values = [f"{avgs[c]:.1f}".ljust(w) for c, w in zip(criteria, widths[1:-1])]
    avg_str = f"{overall:.1f}".ljust(widths[-1])

    row = " | ".join([model.ljust(widths[0])] + values + [avg_str])
    print(f"| {row} |")

print()
print(f"Score files saved in: {score_dir}")
PYEOF

# Cleanup hint
echo ""
echo "To clean up temporary files: rm -rf $SCORE_DIR"
