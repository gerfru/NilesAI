#!/bin/bash

# Niles AI - Interactive Setup
# Intelligentes Setup mit Status-Checks

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Helper functions
echo_step() {
    echo ""
    echo -e "${BLUE}===================================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}===================================================${NC}"
    echo ""
}

echo_success() {
    echo -e "${GREEN}[OK] $1${NC}"
}

echo_error() {
    echo -e "${RED}[ERROR] $1${NC}"
}

echo_warning() {
    echo -e "${YELLOW}[WARN] $1${NC}"
}

echo_info() {
    echo -e "${BLUE}[INFO] $1${NC}"
}

wait_for_user() {
    echo ""
    read -p "Press Enter to continue..."
    echo ""
}

# Change to Niles root directory
cd "$(dirname "$0")/.."

# Header
clear
echo -e "${BLUE}"
cat << "EOF"
+===================================================+
|                                                     |
|              Niles AI Setup                         |
|                                                     |
|         Interactive Installation & Setup            |
|                                                     |
+===================================================+
EOF
echo -e "${NC}"
echo ""
echo "This script will guide you through the complete setup."
echo "It will check what's already configured and only do what's needed."
echo ""
wait_for_user

# Step 1: Check Docker
echo_step "Step 1/6: Docker"

if docker info > /dev/null 2>&1; then
    echo_success "Docker is running"
else
    echo_error "Docker is not running"
    echo ""
    echo "Please:"
    echo "  1. Open Docker Desktop: open -a Docker"
    echo "  2. Wait for Docker to start"
    echo ""
    read -p "Press Enter once Docker is running..."

    if docker info > /dev/null 2>&1; then
        echo_success "Docker is now running"
    else
        echo_error "Docker still not running. Exiting."
        exit 1
    fi
fi

# Step 2: LM Studio
echo_step "Step 2/6: LM Studio"

if [ -d "/Applications/LM Studio.app" ]; then
    echo_success "LM Studio is installed"

    # Check if server is running
    if nc -z localhost 1234 2>/dev/null; then
        echo_success "LM Studio server is running"
    else
        echo_warning "LM Studio server is not running"
        echo ""
        echo "Please:"
        echo "  1. Open LM Studio: open -a 'LM Studio'"
        echo "  2. Download model: Qwen2.5-Coder:7b (MLX 8-bit)"
        echo "  3. Start Server on port 1234"
        echo ""
        echo "You can do this now or later."
        wait_for_user
    fi
else
    echo_warning "LM Studio is not installed"
    echo ""
    echo "Download from: https://lmstudio.ai/download"
    echo ""
    echo "You can install it now or continue and install later."
    wait_for_user
fi

# Step 3: Environment Configuration
echo_step "Step 3/6: Environment Configuration"

if [ -f .env ]; then
    echo_success ".env file already exists"

    # Load environment variables
    set -a
    source .env
    set +a
else
    echo_info "Creating .env file from template..."
    echo ""

    if [ -f .env.example ]; then
        cp .env.example .env
        echo_success ".env file created from .env.example"
        echo ""
        echo_warning "IMPORTANT: Edit .env and set your secrets!"
        echo ""
        echo "Required:"
        echo "  EVOLUTION_POSTGRES_PASSWORD=<your-password>"
        echo "  EVOLUTION_API_KEY=<your-api-key>"
        echo ""
        echo "Optional (for Google OAuth login):"
        echo "  GOOGLE_CLIENT_ID=<from Google Cloud Console>"
        echo "  GOOGLE_CLIENT_SECRET=<from Google Cloud Console>"
        echo "  GOOGLE_ALLOWED_EMAILS=user@gmail.com"
        echo "  SESSION_SECRET=<random-string>"
        echo "  BASE_URL=https://your-host.example.com"
        echo ""
        echo "Opening .env in editor..."
        ${EDITOR:-nano} .env
        echo ""

        # Load after editing
        set -a
        source .env
        set +a
    else
        echo_error ".env.example not found!"
        exit 1
    fi
fi

# Step 4: Docker Services
echo_step "Step 4/6: Docker Services"

if docker ps | grep -q "niles_core"; then
    echo_success "Docker services are already running"
else
    echo_info "Starting Docker services..."
    echo ""

    echo "Building and starting services (this may take a few minutes)..."
    docker compose -f docker/docker-compose.yml --env-file .env up -d --build

    echo ""
    echo "Waiting for services to initialize..."
    sleep 15

    if docker ps | grep -q "niles_core"; then
        echo_success "Services started successfully"
    else
        echo_error "Failed to start services"
        echo ""
        echo "Check logs with: docker compose -f docker/docker-compose.yml --env-file .env logs"
        exit 1
    fi
fi

# Step 5: Verify Niles Core
echo_step "Step 5/6: Niles Core"

if HEALTH=$(curl -sk https://localhost/health 2>&1) && echo "$HEALTH" | grep -q '"status":"ok"'; then
    echo_success "Niles Core is running (https://localhost)"
    echo ""
    echo "Web UI: https://localhost/ui/login"
else
    echo_warning "Niles Core is starting up..."
    echo "Check: docker compose -f docker/docker-compose.yml --env-file .env logs niles_core"
fi

# Step 6: Final Verification
echo_step "Step 6/6: Final Verification"

echo "Running status checks..."
echo ""

# Niles Core
if HEALTH=$(curl -sk https://localhost/health 2>&1) && echo "$HEALTH" | grep -q '"status":"ok"'; then
    echo_success "Niles Core: Running (https://localhost)"
else
    echo_error "Niles Core: Not reachable"
fi

# Evolution API (via Caddy)
if RESPONSE=$(curl -sk https://localhost:8443/ 2>&1) && echo "$RESPONSE" | grep -q "Welcome"; then
    echo_success "Evolution API: Running (https://localhost:8443)"
else
    echo_warning "Evolution API: Not reachable via Caddy"
fi

# WhatsApp
if [ -n "${EVOLUTION_API_KEY:-}" ]; then
    if INSTANCE=$(curl -sk -H "apikey: ${EVOLUTION_API_KEY}" https://localhost:8443/instance/connectionState/niles-whatsapp 2>&1); then
        if echo "$INSTANCE" | grep -q '"state":"open"'; then
            echo_success "WhatsApp: Connected"
        elif echo "$INSTANCE" | grep -q '"state":"connecting"'; then
            echo_warning "WhatsApp: Connecting (scan QR code at https://localhost:8443/manager)"
        else
            echo_warning "WhatsApp: Not configured (setup via https://localhost:8443/manager)"
        fi
    else
        echo_warning "WhatsApp: Instance not found"
    fi
fi

# LM Studio
if nc -z localhost 1234 2>/dev/null; then
    echo_success "LM Studio: Server running"
else
    echo_warning "LM Studio: Not running (start manually)"
fi

# Google OAuth
if [ -n "${GOOGLE_CLIENT_ID:-}" ] && [ -n "${GOOGLE_CLIENT_SECRET:-}" ]; then
    echo_success "Google OAuth: Configured"
else
    echo_info "Google OAuth: Not configured (API-Key login as fallback)"
fi

# Summary
echo ""
echo_step "Setup Complete"

cat << EOF

+===================================================+
|                                                     |
|              Setup Complete                          |
|                                                     |
+===================================================+

Service URLs (HTTPS via Caddy, self-signed):
   - Niles Web UI:       https://localhost/ui/login
   - Evolution Manager:  https://localhost:8443/manager
   - LM Studio API:      http://localhost:1234/v1

Daily Usage:
   ./scripts/start.sh   - Start all services
   ./scripts/stop.sh    - Stop all services
   ./scripts/status.sh  - Check status
   ./scripts/backup.sh  - Backup all data

EOF

echo ""
echo_success "Setup script finished."
echo ""
