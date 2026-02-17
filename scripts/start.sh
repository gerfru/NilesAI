#!/bin/bash

# Niles AI - Start Script
# Startet alle Docker Services

set -e

echo "🚀 Starting Niles AI..."
echo ""

# Change to Niles root directory
cd "$(dirname "$0")/.."

# Check if .env exists
if [ ! -f .env ]; then
    echo "❌ Error: .env file not found!"
    echo ""
    echo "Please create .env from template:"
    echo "  cp .env.example .env"
    echo "  nano .env"
    echo ""
    exit 1
fi

# Start Docker services
echo "📦 Starting Docker containers..."
docker compose -f docker/docker-compose.yml --env-file .env up -d

# Wait for services to be ready
echo "⏳ Waiting for services to start..."
sleep 10

# Check status
echo ""
echo "✅ Services started!"
echo ""
echo "Status:"
docker compose -f docker/docker-compose.yml ps

echo ""
echo "📊 Service URLs:"
echo "  - Niles Core:       http://localhost:8000"
echo "  - Niles API Docs:   http://localhost:8000/docs"
echo "  - n8n:              http://localhost:5678"
echo "  - Evolution API:    http://localhost:8080"
echo "  - Evolution Manager: http://localhost:8080/manager"
echo ""
echo "💡 Next steps:"
echo "  1. Open LM Studio manually: open -a 'LM Studio'"
echo "  2. Start LM Studio Server (Port 1234)"
echo "  3. Open n8n: http://localhost:5678"
echo ""
echo "✨ Niles AI is ready!"
