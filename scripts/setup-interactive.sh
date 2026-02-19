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

# Load environment variables if .env exists
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

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
echo_step "Step 1/8: Docker"

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
echo_step "Step 2/8: LM Studio"

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
echo_step "Step 3/9: Environment Configuration"

if [ -f .env ]; then
    echo_success ".env file already exists"
else
    echo_info "Creating .env file from template..."
    echo ""

    if [ -f .env.example ]; then
        cp .env.example .env
        echo_success ".env file created"
        echo ""
        echo "Default credentials configured:"
        echo "  - Evolution API Key: niles-secure-key-2026"
        echo "  - PostgreSQL Password: evolution_secure_2026"
        echo ""
        echo_warning "IMPORTANT: Change these credentials in production!"
        echo "  Edit: nano .env"
        echo ""

        # Set default values
        echo "EVOLUTION_API_KEY=niles-secure-key-2026" > .env
        echo "EVOLUTION_POSTGRES_PASSWORD=evolution_secure_2026" >> .env

        wait_for_user
    else
        echo_error ".env.example not found!"
        exit 1
    fi
fi

# Step 4: Docker Services
echo_step "Step 4/7: Docker Services"

if docker ps | grep -q "niles_core"; then
    echo_success "Docker services are already running"
else
    echo_info "Starting Docker services..."
    echo ""

    # Pull images first
    echo "Pulling Docker images (this may take a few minutes)..."
    docker compose -f docker/docker-compose.yml --env-file .env pull

    echo ""
    echo "Starting services..."
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

# Step 5: WhatsApp
echo_step "Step 5/7: WhatsApp Integration"

if curl -s -H "apikey: ${EVOLUTION_API_KEY}" \
    http://localhost:8080/instance/connectionState/niles-whatsapp 2>&1 | \
    grep -q '"state":"open"'; then
    echo_success "WhatsApp is connected"
else
    echo_info "WhatsApp needs setup"
    echo ""
    echo "Do you want to set up WhatsApp now?"
    read -p "Setup now? (y/n): " -n 1 -r
    echo ""

    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo ""
        echo "Creating WhatsApp instance..."

        # Create instance
        RESPONSE=$(curl -s -X POST http://localhost:8080/instance/create \
            -H "apikey: ${EVOLUTION_API_KEY}" \
            -H "Content-Type: application/json" \
            -d '{"instanceName":"niles-whatsapp","qrcode":true,"integration":"WHATSAPP-BAILEYS"}')

        if echo "$RESPONSE" | grep -q "instanceName"; then
            echo_success "Instance created"
            echo ""
            echo "Opening Evolution Manager..."
            sleep 2
            open http://localhost:8080/manager
            echo ""
            echo "In the Manager:"
            echo "  1. Login with API Key: ${EVOLUTION_API_KEY}"
            echo "  2. Click on 'niles-whatsapp'"
            echo "  3. Scan QR code with WhatsApp app"
            echo "     (WhatsApp -> Settings -> Linked Devices)"
            echo ""
            wait_for_user

            # Check if connected
            if curl -s -H "apikey: ${EVOLUTION_API_KEY}" \
                http://localhost:8080/instance/connectionState/niles-whatsapp 2>&1 | \
                grep -q '"state":"open"'; then
                echo_success "WhatsApp is now connected!"
            else
                echo_warning "WhatsApp not connected yet"
                echo "You can scan the QR code later at: http://localhost:8080/manager"
            fi
        else
            echo_error "Failed to create instance"
            echo "Details: $RESPONSE"
        fi
    else
        echo_info "Skipping WhatsApp (you can set it up later)"
    fi
fi

# Step 6: Niles Core
echo_step "Step 6/7: Niles Core"

if HEALTH=$(curl -sk https://localhost/health 2>&1) && echo "$HEALTH" | grep -q '"status":"ok"'; then
    echo_success "Niles Core is running (https://localhost)"
    echo ""
    echo "Web UI: https://localhost/ui/chat"
    echo "API Docs: https://localhost/docs"
else
    echo_warning "Niles Core is starting up..."
    echo "Check: docker compose -f docker/docker-compose.yml --env-file .env logs niles_core"
fi

# Step 7: Final Verification
echo_step "Step 7/7: Final Verification"

echo "Running status checks..."
echo ""

# Niles Core
if HEALTH=$(curl -sk https://localhost/health 2>&1) && echo "$HEALTH" | grep -q '"status":"ok"'; then
    echo_success "Niles Core: Running (https://localhost)"
else
    echo_error "Niles Core: Not reachable"
fi

# Evolution API
if curl -s http://localhost:8080 > /dev/null 2>&1 | grep -q "Welcome"; then
    echo_success "Evolution API: Running (http://localhost:8080)"
else
    echo_error "Evolution API: Not reachable"
fi

# WhatsApp
if curl -s -H "apikey: ${EVOLUTION_API_KEY}" \
    http://localhost:8080/instance/connectionState/niles-whatsapp 2>&1 | \
    grep -q '"state":"open"'; then
    echo_success "WhatsApp: Connected"
elif curl -s -H "apikey: ${EVOLUTION_API_KEY}" \
    http://localhost:8080/instance/connectionState/niles-whatsapp 2>&1 | \
    grep -q '"state":"connecting"'; then
    echo_warning "WhatsApp: Connecting (scan QR code)"
else
    echo_warning "WhatsApp: Not configured"
fi

# LM Studio
if nc -z localhost 1234 2>/dev/null; then
    echo_success "LM Studio: Server running"
else
    echo_warning "LM Studio: Not running (start manually)"
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
   - Niles Web UI:       https://localhost/ui/chat
   - Niles API Docs:     https://localhost/docs
   - Evolution Manager:  https://localhost:8443/manager
   - LM Studio API:      http://localhost:1234/v1

Daily Usage:
   ./scripts/start.sh   - Start all services
   ./scripts/stop.sh    - Stop all services
   ./scripts/status.sh  - Check status

EOF

echo ""
echo "Would you like to see the status now?"
read -p "Run status check? (y/n): " -n 1 -r
echo ""

if [[ $REPLY =~ ^[Yy]$ ]]; then
    ./scripts/status.sh
fi

echo ""
echo_success "Setup script finished."
echo ""
