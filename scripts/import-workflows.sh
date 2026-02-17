#!/bin/bash

# Import n8n Workflows via REST API
# Usage: ./import-workflows.sh [workflow-name.json]
#   - Without argument: imports all workflows from workflows/
#   - With argument: imports specific workflow file

set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Configuration
N8N_URL="http://localhost:5678"
WORKFLOWS_DIR="../workflows"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKFLOWS_PATH="$SCRIPT_DIR/$WORKFLOWS_DIR"
ENV_FILE="$SCRIPT_DIR/../.env"

# Load environment variables
if [ -f "$ENV_FILE" ]; then
    source "$ENV_FILE"
fi

# Check if API key is set
if [ -z "$N8N_API_KEY" ]; then
    echo -e "${RED}Error: N8N_API_KEY not found in .env${NC}"
    echo "Please add N8N_API_KEY to $ENV_FILE"
    exit 1
fi

# Check if n8n is running
check_n8n_running() {
    echo -e "${YELLOW}Checking if n8n is running...${NC}"
    if ! curl -s "$N8N_URL" > /dev/null 2>&1; then
        echo -e "${RED}Error: n8n is not running on $N8N_URL${NC}"
        echo "Start n8n first: ./scripts/start.sh"
        exit 1
    fi
    echo -e "${GREEN}n8n is running${NC}"
}

# Get existing workflows from n8n
get_existing_workflows() {
    curl -s "$N8N_URL/api/v1/workflows" \
        -H "Content-Type: application/json" \
        -H "X-N8N-API-KEY: $N8N_API_KEY" 2>/dev/null || echo "[]"
}

# Import or update a single workflow
import_workflow() {
    local workflow_file="$1"
    local workflow_name=$(basename "$workflow_file" .json)

    if [ ! -f "$workflow_file" ]; then
        echo -e "${RED}Error: File not found: $workflow_file${NC}"
        return 1
    fi

    echo -e "${YELLOW}Processing: $workflow_name${NC}"

    # Read workflow JSON and extract only fields allowed for import
    # API only accepts: name, nodes, connections, settings (empty object)
    # Note: exported settings contain fields that are not accepted on import
    local workflow_data=$(cat "$workflow_file" | jq '{name, nodes, connections, settings: {}}')

    # Get workflow name from JSON
    local json_name=$(echo "$workflow_data" | jq -r '.name')

    if [ -z "$json_name" ]; then
        json_name="$workflow_name"
    fi

    echo "  Workflow name: $json_name"

    # Check if workflow already exists
    local existing_workflows=$(get_existing_workflows)
    local existing_id=$(echo "$existing_workflows" | jq -r ".data[] | select(.name == \"$json_name\") | .id" | head -1)

    if [ -n "$existing_id" ]; then
        # Update existing workflow
        echo -e "  ${YELLOW}Workflow exists (ID: $existing_id), updating...${NC}"

        response=$(curl -s -w "\n%{http_code}" -X PUT "$N8N_URL/api/v1/workflows/$existing_id" \
            -H "Content-Type: application/json" \
            -H "X-N8N-API-KEY: $N8N_API_KEY" \
            -d "$workflow_data" 2>/dev/null)

        http_code=$(echo "$response" | tail -n 1)

        if [ "$http_code" = "200" ]; then
            echo -e "  ${GREEN}Workflow updated successfully${NC}"
            return 0
        else
            echo -e "  ${RED}Failed to update workflow (HTTP $http_code)${NC}"
            response_body=$(echo "$response" | sed '$d')
            echo "$response_body"
            return 1
        fi
    else
        # Create new workflow
        echo -e "  ${YELLOW}Creating new workflow...${NC}"

        response=$(curl -s -w "\n%{http_code}" -X POST "$N8N_URL/api/v1/workflows" \
            -H "Content-Type: application/json" \
            -H "X-N8N-API-KEY: $N8N_API_KEY" \
            -d "$workflow_data" 2>/dev/null)

        http_code=$(echo "$response" | tail -n 1)

        if [ "$http_code" = "200" ] || [ "$http_code" = "201" ]; then
            echo -e "  ${GREEN}Workflow created successfully${NC}"
            return 0
        else
            echo -e "  ${RED}Failed to create workflow (HTTP $http_code)${NC}"
            response_body=$(echo "$response" | sed '$d')
            echo "$response_body"
            return 1
        fi
    fi
}

# Main script
main() {
    echo "=========================================="
    echo "  n8n Workflow Import Script"
    echo "=========================================="
    echo ""

    check_n8n_running
    echo ""

    # Check if specific workflow file is provided
    if [ $# -eq 1 ]; then
        # Import single workflow
        workflow_file="$1"

        # If relative path, make it absolute
        if [[ "$workflow_file" != /* ]]; then
            workflow_file="$WORKFLOWS_PATH/$workflow_file"
        fi

        import_workflow "$workflow_file"
        exit_code=$?

        echo ""
        echo "=========================================="
        if [ $exit_code -eq 0 ]; then
            echo -e "${GREEN}Import completed successfully!${NC}"
        else
            echo -e "${RED}Import failed!${NC}"
        fi
        echo "=========================================="

        exit $exit_code
    else
        # Import all workflows
        echo "Importing all workflows from: $WORKFLOWS_PATH"
        echo ""

        if [ ! -d "$WORKFLOWS_PATH" ]; then
            echo -e "${RED}Error: Workflows directory not found: $WORKFLOWS_PATH${NC}"
            exit 1
        fi

        success_count=0
        fail_count=0

        for workflow_file in "$WORKFLOWS_PATH"/*.json; do
            if [ -f "$workflow_file" ]; then
                if import_workflow "$workflow_file"; then
                    ((success_count++))
                else
                    ((fail_count++))
                fi
                echo ""
            fi
        done

        echo "=========================================="
        echo "  Import Summary"
        echo "=========================================="
        echo -e "${GREEN}Successful: $success_count${NC}"
        echo -e "${RED}Failed: $fail_count${NC}"
        echo "=========================================="

        if [ $fail_count -gt 0 ]; then
            exit 1
        fi
    fi
}

main "$@"
