#!/bin/bash

# Niles AI - Backup Script
# Sichert alle Daten: n8n, WhatsApp, Config

set -e

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

# Change to Niles root directory
cd "$(dirname "$0")/.."

# Backup directory with timestamp
BACKUP_DIR="$HOME/Backups/Niles"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_PATH="$BACKUP_DIR/$TIMESTAMP"

echo -e "${BLUE}Niles AI - Backup${NC}"
echo ""
echo "Creating backup at: $BACKUP_PATH"
echo ""

# Create backup directory
mkdir -p "$BACKUP_PATH"

# 1. Backup n8n data
echo "Backing up n8n data..."
if [ -d ~/.n8n ]; then
    tar -czf "$BACKUP_PATH/n8n-data.tar.gz" -C ~ .n8n
    echo -e "${GREEN}n8n data backed up${NC}"
else
    echo "No n8n data found (skipping)"
fi

# 1b. Backup Evolution WhatsApp sessions
echo ""
echo "Backing up WhatsApp sessions..."
if [ -d ~/.evolution ]; then
    tar -czf "$BACKUP_PATH/evolution-data.tar.gz" -C ~ .evolution
    echo -e "${GREEN}WhatsApp sessions backed up${NC}"
else
    echo "No WhatsApp sessions found (skipping)"
fi

# 2. Backup configuration files
echo ""
echo "Backing up configuration..."
cp -r docker "$BACKUP_PATH/"
cp -r Setup "$BACKUP_PATH/" 2>/dev/null || true
cp -r scripts "$BACKUP_PATH/" 2>/dev/null || true
if [ -f .env ]; then
    cp .env "$BACKUP_PATH/"
fi
echo -e "${GREEN}Configuration backed up${NC}"

# 3. Backup Docker volumes (only PostgreSQL)
echo ""
echo "Backing up Docker volumes..."

# Evolution PostgreSQL
if docker volume inspect docker_evolution_postgres > /dev/null 2>&1; then
    docker run --rm \
        -v docker_evolution_postgres:/data \
        -v "$BACKUP_PATH":/backup \
        alpine tar czf /backup/evolution-postgres.tar.gz -C /data .
    echo -e "${GREEN}PostgreSQL data backed up${NC}"
elif docker volume inspect evolution_postgres > /dev/null 2>&1; then
    docker run --rm \
        -v evolution_postgres:/data \
        -v "$BACKUP_PATH":/backup \
        alpine tar czf /backup/evolution-postgres.tar.gz -C /data .
    echo -e "${GREEN}PostgreSQL data backed up${NC}"
fi

# 4. Create restore script
echo ""
echo "Creating restore script..."

cat > "$BACKUP_PATH/restore.sh" << 'RESTORE_EOF'
#!/bin/bash
# Restore Niles AI from backup

set -e

echo "Restoring Niles AI backup..."
echo ""

BACKUP_DIR="$(dirname "$0")"

# Restore n8n
if [ -f "$BACKUP_DIR/n8n-data.tar.gz" ]; then
    echo "Restoring n8n data..."
    tar -xzf "$BACKUP_DIR/n8n-data.tar.gz" -C ~
    echo "n8n data restored"
fi

# Restore WhatsApp sessions
if [ -f "$BACKUP_DIR/evolution-data.tar.gz" ]; then
    echo ""
    echo "Restoring WhatsApp sessions..."
    tar -xzf "$BACKUP_DIR/evolution-data.tar.gz" -C ~
    echo "WhatsApp sessions restored"
fi

# Restore config
if [ -d "$BACKUP_DIR/docker" ]; then
    echo ""
    echo "Restoring configuration..."
    cp -r "$BACKUP_DIR/docker" ~/Documents/Niles/
    if [ -d "$BACKUP_DIR/Setup" ]; then
        cp -r "$BACKUP_DIR/Setup" ~/Documents/Niles/
    fi
    if [ -d "$BACKUP_DIR/scripts" ]; then
        cp -r "$BACKUP_DIR/scripts" ~/Documents/Niles/
    fi
    echo "Configuration restored"
fi

# Restore Docker volumes (only PostgreSQL)
echo ""
echo "Restoring Docker volumes..."

# Create volumes if they don't exist
docker volume create evolution_postgres 2>/dev/null || true

# Restore PostgreSQL
if [ -f "$BACKUP_DIR/evolution-postgres.tar.gz" ]; then
    docker run --rm \
        -v evolution_postgres:/data \
        -v "$BACKUP_DIR":/backup \
        alpine sh -c "cd /data && tar xzf /backup/evolution-postgres.tar.gz"
    echo "PostgreSQL data restored"
fi

echo ""
echo "Restore complete."
echo ""
echo "Next steps:"
echo "  1. cd ~/Documents/Niles"
echo "  2. ./scripts/start.sh"
echo "  3. Open LM Studio and start server"
RESTORE_EOF

chmod +x "$BACKUP_PATH/restore.sh"

# 5. Create backup info file
cat > "$BACKUP_PATH/backup-info.txt" << EOF
Niles AI Backup
===============

Created: $(date)
Hostname: $(hostname)
Docker Version: $(docker --version)

Contents:
- n8n data (~/.n8n)
- WhatsApp sessions (~/.evolution)
- PostgreSQL Docker volume
- Configuration files (docker/, Setup/, scripts/)
- Restore script (restore.sh)

To restore:
1. Copy this folder to new Mac
2. Run: ./restore.sh
3. Follow instructions in Setup/README.md for:
   - Google Calendar OAuth (needs re-auth)
   - WhatsApp QR code (needs re-scan)

Backup Size: $(du -sh "$BACKUP_PATH" | cut -f1)
EOF

# 6. Create compressed archive
echo ""
echo "Creating compressed archive..."
cd "$BACKUP_DIR"
tar -czf "niles-backup-$TIMESTAMP.tar.gz" "$TIMESTAMP"
ARCHIVE_SIZE=$(du -h "niles-backup-$TIMESTAMP.tar.gz" | cut -f1)

echo -e "${GREEN}Archive created: niles-backup-$TIMESTAMP.tar.gz${NC}"
echo ""

# 7. Cleanup old backups (keep last 7)
echo "Cleaning up old backups (keeping last 7)..."
cd "$BACKUP_DIR"
ls -t niles-backup-*.tar.gz 2>/dev/null | tail -n +8 | xargs rm -f 2>/dev/null || true
ls -td [0-9]* 2>/dev/null | tail -n +8 | xargs rm -rf 2>/dev/null || true
echo -e "${GREEN}Old backups cleaned up${NC}"

# Summary
echo ""
echo -e "${GREEN}=======================================${NC}"
echo -e "${GREEN}Backup Complete${NC}"
echo -e "${GREEN}=======================================${NC}"
echo ""
echo "Backup location:"
echo "   $BACKUP_PATH"
echo ""
echo "Compressed archive:"
echo "   $BACKUP_DIR/niles-backup-$TIMESTAMP.tar.gz"
echo "   Size: $ARCHIVE_SIZE"
echo ""
echo "Included:"
echo "   - n8n workflows & credentials (~/.n8n)"
echo "   - WhatsApp sessions (~/.evolution)"
echo "   - PostgreSQL database (Docker volume)"
echo "   - Configuration files (docker/, scripts/, Setup/)"
echo "   - Restore script"
echo ""
echo "To restore on another Mac:"
echo "   1. Copy: niles-backup-$TIMESTAMP.tar.gz"
echo "   2. Extract: tar -xzf niles-backup-$TIMESTAMP.tar.gz"
echo "   3. Run: cd $TIMESTAMP && ./restore.sh"
echo ""
echo "Manual steps after restore:"
echo "   - Google Calendar: Re-authenticate OAuth"
echo "   - LM Studio: Re-download model"
echo ""
echo "No QR code scan needed (WhatsApp sessions included)."
echo ""
