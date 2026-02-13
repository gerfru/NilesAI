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
    echo -e "${GREEN}✅ $1${NC}"
}

echo_error() {
    echo -e "${RED}❌ $1${NC}"
}

echo_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

echo_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
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
╔═══════════════════════════════════════════════════╗
║                                                   ║
║             🤖  Niles AI Setup  🤖                ║
║                                                   ║
║         Interactive Installation & Setup          ║
║                                                   ║
╚═══════════════════════════════════════════════════╝
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
echo_step "Step 4/9: Docker Services"

if docker ps | grep -q "niles_n8n"; then
    echo_success "Docker services are already running"
else
    echo_info "Starting Docker services..."
    echo ""

    # Pull images first
    echo "Pulling Docker images (this may take a few minutes)..."
    docker compose -f docker/docker-compose.yml --env-file .env pull

    echo ""
    echo "Starting services..."
    docker compose -f docker/docker-compose.yml --env-file .env up -d

    echo ""
    echo "Waiting for services to initialize..."
    sleep 15

    if docker ps | grep -q "niles_n8n"; then
        echo_success "Services started successfully"
    else
        echo_error "Failed to start services"
        echo ""
        echo "Check logs with: docker compose -f docker/docker-compose.yml --env-file .env logs"
        exit 1
    fi
fi

# Step 4: n8n Setup
echo_step "Step 4/8: n8n Setup"

if curl -s http://localhost:5678 > /dev/null 2>&1; then
    echo_success "n8n is reachable"

    # Check if user exists (simple check via .n8n directory)
    if [ -f ~/.n8n/database.sqlite ]; then
        echo_success "n8n is already configured"
    else
        echo_warning "n8n needs initial configuration"
        echo ""
        echo "Opening n8n in browser..."
        sleep 2
        open http://localhost:5678
        echo ""
        echo "Please:"
        echo "  1. Create your account (stored locally)"
        echo "  2. Skip the tour if prompted"
        echo ""
        echo "Come back here when done."
        wait_for_user

        if [ -f ~/.n8n/database.sqlite ]; then
            echo_success "n8n is now configured"
        else
            echo_warning "n8n setup skipped - you can do it later"
        fi
    fi
else
    echo_error "n8n is not reachable"
    echo "Check: docker compose -f docker/docker-compose.yml --env-file .env logs n8n"
fi

# Step 5: Google Calendar
echo_step "Step 5/8: Google Calendar Integration"

echo_info "Checking Google Calendar connection..."
echo ""
echo "This requires manual setup in Google Cloud Console."
echo ""
echo "Documentation: Setup/03-google-calendar.md"
echo ""
echo "Do you want to set up Google Calendar now?"
read -p "Setup now? (y/n): " -n 1 -r
echo ""

if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo ""
    echo "Opening documentation..."
    open Setup/03-google-calendar.md
    echo ""
    echo "Steps:"
    echo "  1. Go to: https://console.cloud.google.com"
    echo "  2. Create project: 'Niles AI'"
    echo "  3. Enable Google Calendar API"
    echo "  4. Create OAuth Client (Web Application)"
    echo "  5. Add redirect URI from n8n"
    echo "  6. Configure in n8n: http://localhost:5678"
    echo ""
    echo "This will take 10-15 minutes."
    echo ""
    wait_for_user
    echo_success "Google Calendar setup marked as done"
else
    echo_info "Skipping Google Calendar (you can set it up later)"
fi

# Step 6: mailbox.org CalDAV
echo_step "Step 6/8: mailbox.org CalDAV"

echo_info "Checking mailbox.org CalDAV..."
echo ""
echo "This requires your mailbox.org account."
echo ""
echo "Documentation: Setup/03-mailbox-caldav.md"
echo ""
echo "Do you want to set up mailbox.org CalDAV now?"
read -p "Setup now? (y/n): " -n 1 -r
echo ""

if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo ""
    echo "Opening documentation..."
    open Setup/03-mailbox-caldav.md
    echo ""
    echo "Steps:"
    echo "  1. Get CalDAV URL from mailbox.org calendar"
    echo "  2. Create workflow in n8n"
    echo "  3. Test calendar event creation"
    echo ""
    echo "This will take 5-10 minutes."
    echo ""
    wait_for_user
    echo_success "mailbox.org CalDAV setup marked as done"
else
    echo_info "Skipping mailbox.org CalDAV (optional)"
fi

# Step 7: WhatsApp
echo_step "Step 7/8: WhatsApp Integration"

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
            echo "     (WhatsApp → Settings → Linked Devices)"
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

# Step 8: Final Verification
echo_step "Step 8/8: Final Verification"

echo "Running status checks..."
echo ""

# n8n
if curl -s http://localhost:5678 > /dev/null 2>&1; then
    echo_success "n8n: Running (http://localhost:5678)"
else
    echo_error "n8n: Not reachable"
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
echo_step "Setup Complete!"

cat << EOF

╔═══════════════════════════════════════════════════╗
║                                                   ║
║           ✨  Setup Complete!  ✨                 ║
║                                                   ║
╚═══════════════════════════════════════════════════╝

📊 Service URLs:
   - n8n:               http://localhost:5678
   - Evolution Manager:  http://localhost:8080/manager
   - LM Studio API:      http://localhost:1234/v1

📚 Documentation:
   - Setup Guide:        Setup/README.md
   - Google Calendar:    Setup/03-google-calendar.md
   - mailbox.org:        Setup/03-mailbox-caldav.md
   - WhatsApp:           Setup/05-whatsapp-evolution.md

🚀 Daily Usage:
   ./scripts/start.sh   - Start all services
   ./scripts/stop.sh    - Stop all services
   ./scripts/status.sh  - Check status

📝 Next Steps:
   1. Configure remaining integrations
   2. Create AI Agent workflows
   3. Read Setup/06-ai-agent.md

💡 Get Help:
   - Setup/README.md
   - n8n Community: https://community.n8n.io/

EOF

echo ""
echo "Would you like to see the status now?"
read -p "Run status check? (y/n): " -n 1 -r
echo ""

if [[ $REPLY =~ ^[Yy]$ ]]; then
    ./scripts/status.sh
fi

echo ""
echo_success "Setup script finished!"
echo ""
