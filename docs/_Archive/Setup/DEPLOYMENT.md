# Niles AI - Deployment Guide

Schnelles Deployment des kompletten Niles AI Setups via Scripts.

> **Important:** This guide uses example credentials (`niles-secure-key-2026`, `evolution_secure_2026`).
Your actual credentials are configured in `.env` file at the project root.

## Übersicht

Das Niles-Setup besteht aus:
- **Docker Services:** n8n, Evolution API, PostgreSQL
- **LM Studio:** Lokal auf dem Mac (manuell zu starten)
- **Management Scripts:** Automatisierung des Deployments

## Dateien

```
Niles/
├── docker/
│   └── docker-compose.yml     # Alle Docker Services
├── workflows/
│   ├── Niles-hybrid-with-contacts.json  # Haupt-Workflow (WhatsApp AI Agent)
│   └── sync-contacts.json     # CardDAV → PostgreSQL Kontakt-Sync
├── scripts/
│   ├── setup-interactive.sh   # Interaktives Setup mit Checks
│   ├── start.sh               # Tägliches Starten
│   ├── stop.sh                # Stoppen
│   ├── status.sh              # Status-Check
│   ├── backup.sh              # Backup erstellen
│   ├── cleanup.sh             # Komplett zurücksetzen (VORSICHT!)
│   └── import-workflows.sh    # Workflows via n8n API importieren
├── docs/
│   └── Setup/                 # Detaillierte Dokumentation
└── .env                       # API Keys & Passwörter (nicht in Git)
```

## Schnellstart (Neues System)

### 1. Repository klonen / Ordner kopieren

```bash
# Falls Git-Repo:
git clone https://github.com/gerfru/NilesAI.git ~/Documents/Niles
cd ~/Documents/Niles

# Falls lokale Kopie:
# Kopiere den kompletten Niles-Ordner
```

### 2. Voraussetzungen prüfen

**Installiert:**
- Docker Desktop
- LM Studio (optional, aber empfohlen)
- Tailscale (optional, für Remote-Zugriff)

**Docker starten:**
```bash
open -a Docker
```

### 3. Setup ausführen

```bash
./scripts/setup-interactive.sh
```

Das Script:
- ✅ Prüft ob Docker läuft
- ✅ Zieht Docker Images
- ✅ Startet alle Container
- ✅ Zeigt Next Steps

### 4. LM Studio einrichten (manuell)

```bash
open -a "LM Studio"
```

1. Modell herunterladen: **Qwen2.5-Coder:7b (MLX 8-bit)**
2. Server starten: Port **1234**

### 5. Weitere Konfiguration

Folge den Setup-Anleitungen in `Setup/`:
- [03-google-calendar.md](Setup/03-google-calendar.md) - Google Calendar OAuth
- [03-mailbox-caldav.md](Setup/03-mailbox-caldav.md) - Lokaler Kalender
- [05-whatsapp-evolution.md](Setup/05-whatsapp-evolution.md) - WhatsApp QR-Code scannen

## Tägliche Nutzung

### Starten

```bash
./scripts/start.sh
```

Startet:
- n8n (Port 5678)
- Evolution API (Port 8080)
- PostgreSQL

**LM Studio manuell starten:**
```bash
open -a "LM Studio"
# → Server auf Port 1234 starten
```

### Status prüfen

```bash
./scripts/status.sh
```

Zeigt:
- ✅/❌ n8n Status
- ✅/❌ Evolution API Status
- ✅/❌ WhatsApp Verbindung
- ✅/❌ LM Studio Server

### Stoppen

```bash
./scripts/stop.sh
```

Stoppt alle Docker Container (Daten bleiben erhalten).

## Problembehandlung

### Docker läuft nicht

```bash
# Docker Desktop öffnen
open -a Docker

# Warten bis Docker läuft
docker ps
```

### Services starten nicht

```bash
# Logs ansehen
docker compose -f docker/docker-compose.yml logs

# Einzelnen Service neu starten
docker compose -f docker/docker-compose.yml restart n8n
docker compose -f docker/docker-compose.yml restart evolution_api
```

### WhatsApp Verbindung verloren

1. Evolution Manager öffnen: http://localhost:8080/manager
2. Login: API Key `niles-secure-key-2026`
3. QR-Code neu scannen

Oder via Script:
```bash
# Instance neu erstellen
curl -X DELETE http://localhost:8080/instance/logout/niles-whatsapp \
  -H "apikey: niles-secure-key-2026"

curl -X DELETE http://localhost:8080/instance/delete/niles-whatsapp \
  -H "apikey: niles-secure-key-2026"

curl -X POST http://localhost:8080/instance/create \
  -H "apikey: niles-secure-key-2026" \
  -H "Content-Type: application/json" \
  -d '{"instanceName":"niles-whatsapp","qrcode":true,"integration":"WHATSAPP-BAILEYS"}'
```

### Port schon belegt

```bash
# Prüfe welcher Prozess Port 5678 nutzt
lsof -i :5678

# Oder Port 8080
lsof -i :8080

# Stoppe alte Container
docker ps
docker stop <container-id>
```

## Backup & Restore

### Backup erstellen

**Automatisches Backup:**

```bash
./scripts/backup.sh
```

Erstellt komplettes Backup mit:

- n8n Daten (~/.n8n)
- Docker Volumes (WhatsApp, PostgreSQL)
- Konfiguration (docker/docker-compose.yml, Setup/, scripts/)
- Restore-Script

**Manuelles Backup:**

```bash
# n8n Daten
tar -czf niles-backup-$(date +%Y%m%d).tar.gz \
  ~/.n8n \
  docker/ \
  scripts/ \
  Setup/

# Docker Volumes
docker run --rm -v evolution_instances:/data -v $(pwd):/backup \
  alpine tar czf /backup/evolution-backup-$(date +%Y%m%d).tar.gz /data
```

### Restore

```bash
# n8n Daten
tar -xzf niles-backup-YYYYMMDD.tar.gz -C ~/

# Docker Volumes
docker volume create evolution_instances
docker run --rm -v evolution_instances:/data -v $(pwd):/backup \
  alpine tar xzf /backup/evolution-backup-YYYYMMDD.tar.gz -C /data --strip 1
```

## Komplettes Reset

**⚠️ ACHTUNG: Löscht ALLE Daten!**

```bash
./scripts/cleanup.sh
```

Das Script:
1. Fragt nach Bestätigung (`yes`)
2. Stoppt alle Container
3. Löscht alle Volumes
4. Behält ~/.n8n als Backup

Um **wirklich alles** zu löschen:
```bash
./scripts/cleanup.sh
rm -rf ~/.n8n  # Vorsicht!
```

## Deployment auf neuem Mac

### 1. Kopiere Niles-Ordner

```bash
# Via USB-Stick, AirDrop, oder Git
cp -r /Volumes/USB/Niles ~/Documents/
cd ~/Documents/Niles
```

### 2. Docker installieren

```bash
# Download: https://www.docker.com/products/docker-desktop
# Oder via Homebrew:
brew install --cask docker
```

### 3. Setup ausführen

```bash
./scripts/setup-interactive.sh
```

### 4. LM Studio installieren & einrichten

```bash
# Download: https://lmstudio.ai/download
# Modell herunterladen: Qwen2.5-Coder:7b (MLX)
```

### 5. Credentials wiederherstellen

**n8n:**
- Falls ~/.n8n Backup vorhanden → Kopieren
- Sonst → Google Calendar, mailbox.org neu konfigurieren

**WhatsApp:**
- QR-Code neu scannen (Sessions gehen verloren)

## Autostart (macOS)

### Docker Autostart

Docker Desktop → Settings → General:
- ✅ Start Docker Desktop when you log in

### n8n & Evolution API Autostart

Bereits konfiguriert via `restart: unless-stopped` in docker/docker-compose.yml

### LM Studio Autostart

**Option 1: Login Items (einfach)**

System Settings → Users → Login Items:
- **+** → LM Studio.app hinzufügen

**Option 2: LaunchAgent (automatischer Server-Start)**

Siehe [Setup/07-production.md](Setup/07-production.md) für Details.

## Umgebungsvariablen anpassen

### API Keys ändern

In `.env` im Projekt-Root:

```bash
N8N_API_KEY=dein-n8n-api-key           # für import-workflows.sh
EVOLUTION_API_KEY=dein-evolution-key     # Evolution API + n8n Workflows
EVOLUTION_POSTGRES_PASSWORD=dein-pw      # PostgreSQL
```

**WICHTIG:** Nach Änderung Container neu starten!

```bash
docker compose -f docker/docker-compose.yml down
docker compose -f docker/docker-compose.yml up -d
```

### Ports ändern

```yaml
ports:
  - "5679:5678"  # n8n auf Port 5679
  - "8081:8080"  # Evolution API auf Port 8081
```

## Performance-Optimierung

### RAM-Limits setzen

```yaml
services:
  n8n:
    mem_limit: 512m

  evolution_api:
    mem_limit: 256m
```

### Logs begrenzen

```yaml
services:
  n8n:
    logging:
      options:
        max-size: "10m"
        max-file: "3"
```

## Monitoring

### Docker Stats

```bash
docker stats
```

### Disk Usage

```bash
docker system df
```

### Logs ansehen

```bash
# Alle Services
docker compose -f docker/docker-compose.yml logs -f

# Einzelner Service
docker compose -f docker/docker-compose.yml logs -f n8n
docker compose -f docker/docker-compose.yml logs -f evolution_api
```

## Nächste Schritte

1. ✅ Setup abgeschlossen
2. → [AI Agent erstellen](Setup/06-ai-agent.md)
3. → [Produktivbetrieb](Setup/07-production.md)

## Support

- Setup-Probleme: Siehe `Setup/README.md`
- Docker-Probleme: `docker compose -f docker/docker-compose.yml logs`
- n8n Community: https://community.n8n.io/
- Evolution API: https://github.com/EvolutionAPI/evolution-api

## Lizenz

Open Source - für persönlichen Gebrauch
