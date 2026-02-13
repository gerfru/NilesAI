# Phase 6: Produktivbetrieb & Autostart

## Übersicht

Konfiguration für automatischen Start aller Komponenten und Backup-Strategie.

**Status:** Noch nicht implementiert

## Geplante Schritte

### 1. Docker Autostart

```bash
# Docker Desktop → Settings → General
# ✅ "Start Docker Desktop when you log in"

# n8n & Radicale werden automatisch gestartet (--restart unless-stopped)

# Überprüfen:
docker ps
```

### 2. LM Studio Autostart

**Via LaunchAgent:**
```bash
cat > ~/Library/LaunchAgents/ai.lmstudio.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>ai.lmstudio</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/open</string>
        <string>-a</string>
        <string>LM Studio</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
</dict>
</plist>
EOF

launchctl load ~/Library/LaunchAgents/ai.lmstudio.plist
```

### 3. Tailscale Remote-Zugriff

```bash
# Tailscale läuft bereits

# n8n via Tailscale erreichbar:
# https://[mac-mini-tailscale-ip]:5678

# Optional: Tailscale Funnel für HTTPS
tailscale funnel 5678  # n8n
```

### 4. Backup-Strategie

```bash
# Tägliches Backup-Script
cat > ~/backup-niles.sh << 'EOF'
#!/bin/bash
BACKUP_DIR=~/Backups/Niles
DATE=$(date +%Y-%m-%d)

mkdir -p "$BACKUP_DIR/$DATE"

# n8n Daten
cp -r ~/.n8n "$BACKUP_DIR/$DATE/n8n"

# LM Studio Config
cp -r ~/Library/Application\ Support/LM\ Studio "$BACKUP_DIR/$DATE/lm-studio"

# Komprimieren
tar -czf "$BACKUP_DIR/niles-$DATE.tar.gz" "$BACKUP_DIR/$DATE"
rm -rf "$BACKUP_DIR/$DATE"

# Alte Backups löschen (älter als 30 Tage)
find "$BACKUP_DIR" -name "niles-*.tar.gz" -mtime +30 -delete

echo "Backup completed: niles-$DATE.tar.gz"
EOF

chmod +x ~/backup-niles.sh

# Via cron täglich um 2 Uhr
crontab -e
# Füge hinzu:
# 0 2 * * * ~/backup-niles.sh
```

## Verifikation

- [ ] Docker startet automatisch beim Login
- [ ] n8n Container läuft nach Reboot
- [ ] LM Studio startet automatisch
- [ ] LM Studio Server läuft auf Port 1234
- [ ] Tailscale-Zugriff funktioniert remote
- [ ] Backup-Script läuft täglich

## Resource Management

### RAM-Nutzung (16 GB Mac Mini M4)

| Komponente | RAM-Verbrauch |
|------------|---------------|
| macOS | ~3 GB |
| LM Studio (Qwen2.5:7b) | ~8 GB |
| n8n (Docker) | ~500 MB |
| Chrome/Firefox | ~2 GB |
| **Gesamt** | ~13.5 GB |

### Disk-Nutzung

| Komponente | Speicher |
|------------|----------|
| LM Studio + Modelle | ~15 GB |
| Docker | ~5 GB |
| n8n Workflows | ~500 MB |
| **Gesamt** | ~20 GB |

## Troubleshooting

### System langsam nach Autostart

- Warte 2-3 Minuten bis alle Services geladen sind
- LM Studio Modell lädt im Hintergrund

### LM Studio Server startet nicht automatisch

- Manuell in LM Studio: Server starten
- Für automatischen Server-Start: AppleScript in LaunchAgent erweitern

### Docker Container laufen nicht nach Reboot

```bash
# Manuell starten:
docker start n8n

# Autostart prüfen:
docker inspect n8n | grep RestartPolicy
```

## Nächste Schritte

- [x] Setup abgeschlossen
- [ ] Regelmäßige Nutzung & Optimierung
- [ ] System-Prompt iterativ verbessern
- [ ] Weitere Tools hinzufügen (optional)
