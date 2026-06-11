#!/bin/bash
set -euo pipefail

echo "Running database migrations..."
python -m niles.migrate

echo "Starting Niles Core..."
exec uvicorn niles.main:app --host 0.0.0.0 --port ${PORT:-8000}
