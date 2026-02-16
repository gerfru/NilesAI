# Phase 5: WhatsApp Integration via Evolution API

> **Important:** This guide uses example credentials (`niles-secure-key-2026`, `evolution_secure_2026`). Your actual credentials are configured in `.env` file. The docker-compose.yml uses environment variables from `.env`.

## Übersicht

Integration von WhatsApp via Evolution API (self-hosted) für Nachrichten-Management durch den AI-Agenten.

**Methode:** Evolution API v2.3.7 mit PostgreSQL + Docker Compose

**Status:** ✅ Funktioniert (getestet Februar 2026)

## Was ist Evolution API?

- Self-hosted WhatsApp Gateway mit REST API
- Multi-Device Support (wie WhatsApp Web)
- Web-Manager UI für QR-Code Scanning
- Open Source & kostenlos
- Benötigt PostgreSQL-Datenbank

## Voraussetzungen

- Docker & Docker Compose installiert
- n8n läuft auf Port 5678
- WhatsApp Account (mit QR-Code Zugriff)
- ~500 MB freier Disk Space

## Setup

### 1. Docker Compose Datei erstellen

Erstelle: `/Users/gerfru/Documents/Niles/docker-compose-evolution.yml`

```yaml
version: '3.9'

services:
  postgres:
    container_name: evolution_postgres
    image: postgres:15-alpine
    restart: unless-stopped
    environment:
      POSTGRES_USER: evolution
      POSTGRES_PASSWORD: evolution_secure_2026
      POSTGRES_DB: evolution_db
    volumes:
      - evolution_postgres:/var/lib/postgresql/data
    networks:
      - evolution_network

  evolution-api:
    container_name: evolution_api
    image: evoapicloud/evolution-api:v2.3.7
    restart: unless-stopped
    ports:
      - "8080:8080"
    environment:
      # API Authentication
      AUTHENTICATION_API_KEY: "niles-secure-key-2026"

      # Database Configuration
      DATABASE_PROVIDER: "postgresql"
      DATABASE_CONNECTION_URI: "postgresql://evolution:evolution_secure_2026@postgres:5432/evolution_db?schema=evolution_api"
      DATABASE_CONNECTION_CLIENT_NAME: "niles_evolution"

      # Data Persistence (minimal)
      DATABASE_SAVE_DATA_INSTANCE: "true"
      DATABASE_SAVE_DATA_NEW_MESSAGE: "false"
      DATABASE_SAVE_MESSAGE_UPDATE: "false"
      DATABASE_SAVE_DATA_CONTACTS: "false"
      DATABASE_SAVE_DATA_CHATS: "false"

      # Disable Redis Cache (optional)
      CACHE_REDIS_ENABLED: "false"

      # WhatsApp Version (leave empty for auto-update)
      CONFIG_SESSION_PHONE_VERSION: ""
    volumes:
      - evolution_instances:/evolution/instances
    networks:
      - evolution_network
    depends_on:
      - postgres

volumes:
  evolution_postgres:
  evolution_instances:

networks:
  evolution_network:
    driver: bridge
```

**WICHTIG:**
- `AUTHENTICATION_API_KEY` durch ein sicheres Passwort ersetzen!
- `POSTGRES_PASSWORD` auch ändern (und im `DATABASE_CONNECTION_URI` anpassen)

### 2. Evolution API starten

```bash
cd /Users/gerfru/Documents/Niles
docker compose -f docker/docker-compose.yml up -d
```

**Container prüfen:**
```bash
docker ps | grep evolution
# Sollte 2 Container zeigen: evolution_api und evolution_postgres
```

**Logs checken:**
```bash
docker logs evolution_api

# Erwartete Ausgabe:
# [Evolution API] v2.1.1 - INFO [WA MODULE] Module - ON
# [Evolution API] v2.1.1 - INFO [PrismaRepository] Repository:Prisma - ON
# [Evolution API] v2.1.1 - LOG [SERVER] HTTP - ON: 8080
```

**Status testen:**
```bash
curl http://localhost:8080/

# Erwartete Antwort:
# {"status":200,"message":"Welcome to the Evolution API, it is working!","version":"2.1.1"}
```

### 3. WhatsApp Instance erstellen

```bash
curl -X POST http://localhost:8080/instance/create \
  -H "apikey: niles-secure-key-2026" \
  -H "Content-Type: application/json" \
  -d '{
    "instanceName": "niles-whatsapp",
    "qrcode": true,
    "integration": "WHATSAPP-BAILEYS"
  }'
```

**Erwartete Antwort:**
```json
{
  "instance": {
    "instanceName": "niles-whatsapp",
    "instanceId": "...",
    "status": "connecting"
  },
  "qrcode": {
    "code": "...",
    "base64": "data:image/png;base64,..."
  }
}
```

### 4. QR-Code scannen

**Option A: Via Evolution Manager (empfohlen)**

1. Browser öffnen: **http://localhost:8080/manager/login**

   Oder via Tailscale: **http://[mac-mini-tailscale-ip]:8080/manager/login**

2. Login:
   - **Server URL:** `http://localhost:8080` (oder Tailscale IP)
   - **API Key Global:** `niles-secure-key-2026`

3. Auf **"Login"** klicken

4. Instance **"niles-whatsapp"** in der Liste finden und anklicken

5. **QR-Code** wird angezeigt

**Mit WhatsApp-App scannen:**
1. WhatsApp öffnen
2. **Einstellungen** → **Verknüpfte Geräte**
3. **"Gerät verknüpfen"**
4. QR-Code aus dem Manager scannen

**Verbindungsstatus prüfen:**
```bash
curl -s http://localhost:8080/instance/connectionState/niles-whatsapp \
  -H "apikey: niles-secure-key-2026"

# Sollte zurückgeben:
# {"instance":{"instanceName":"niles-whatsapp","state":"open"}}
```

**"state":"open"** = ✅ Erfolgreich verbunden!

## n8n Integration

### Schritt 1: Test-Workflow erstellen

1. **n8n** öffnen: http://localhost:5678
2. **Workflows** → **"+ Add workflow"**
3. **Workflow-Name:** "WhatsApp Test"

### Schritt 2: Manual Trigger

1. **"+ Add first step"** → **"Manual Trigger"**
2. Rechts → **"Test step"** → **"Edit Test Event"**
3. **"Manually"** auswählen
4. JSON:

```json
{
  "phone_number": "4366412345678",
  "message": "Test von Niles 🤖"
}
```

**Telefonnummer-Format:**
- Ländercode + Nummer
- **OHNE** + Zeichen
- **OHNE** Leerzeichen
- Beispiel Österreich: `4366412345678`
- Beispiel Deutschland: `491701234567`

5. **"Save test data"**

### Schritt 3: HTTP Request Node

1. **+** Button rechts vom Manual Trigger → **"HTTP Request"**

2. **Parameters:**
   - **Method:** `POST`
   - **URL:** `http://host.docker.internal:8080/message/sendText/niles-whatsapp`
   - **Authentication:** `None`

3. **Send Headers:** ✅ Aktivieren
   - **+ Add Header** (2x für 2 Header):

     Header 1:
     - **Name:** `apikey`
     - **Value:** `niles-secure-key-2026`

     Header 2:
     - **Name:** `Content-Type`
     - **Value:** `application/json`

4. **Send Body:** ✅ Aktivieren
   - **Body Content Type:** `JSON`
   - **Specify Body:** `Using JSON`
   - **JSON:**

```json
{
  "number": "{{ $json.phone_number }}",
  "text": "{{ $json.message }}"
}
```

### Schritt 4: Workflow testen

1. **"Save"** (oben rechts)
2. **"Test workflow"** (oben rechts)
3. **Erwartetes Ergebnis:**
   - ✅ Grüner Haken beim HTTP Request Node
   - ✅ WhatsApp-Nachricht kommt auf deinem Handy an!

## Wichtige API-Endpunkte

| Endpunkt | Methode | Beschreibung |
|----------|---------|--------------|
| `/instance/create` | POST | Instance erstellen |
| `/instance/connectionState/{instance}` | GET | Verbindungsstatus prüfen |
| `/instance/logout/{instance}` | DELETE | Instance abmelden |
| `/instance/delete/{instance}` | DELETE | Instance löschen |
| `/message/sendText/{instance}` | POST | Textnachricht senden |
| `/message/sendMedia/{instance}` | POST | Bild/Video senden |

**API Key immer als Header mitgeben:**
```
apikey: niles-secure-key-2026
```

## Wichtige Dateien & Volumes

- **Docker Compose:** `/Users/gerfru/Documents/Niles/docker-compose-evolution.yml`
- **Docker Volumes:**
  - `evolution_postgres` - PostgreSQL Daten
  - `evolution_instances` - WhatsApp Sessions
- **n8n Workflow:** In n8n UI gespeichert

## Verifikation

- [x] PostgreSQL Container läuft
- [x] Evolution API Container läuft auf Port 8080
- [x] WhatsApp Instance "niles-whatsapp" erstellt
- [x] QR-Code gescannt, Status "open"
- [x] Test-Nachricht erfolgreich gesendet
- [x] n8n Workflow funktioniert

## Troubleshooting

### QR-Code wird nicht angezeigt / "count":0

**Ursache:** WhatsApp Web Version im Container ist veraltet

**Lösung:**
1. In `docker-compose-evolution.yml` sicherstellen dass `CONFIG_SESSION_PHONE_VERSION: ""` gesetzt ist (leer = auto-update)
2. Container neu starten:
```bash
docker compose -f docker/docker-compose.yml down
docker compose -f docker/docker-compose.yml up -d
```
3. Instance neu erstellen:
```bash
# Alte Instance löschen
curl -X DELETE http://localhost:8080/instance/logout/niles-whatsapp \
  -H "apikey: niles-secure-key-2026"
curl -X DELETE http://localhost:8080/instance/delete/niles-whatsapp \
  -H "apikey: niles-secure-key-2026"

# Neue Instance erstellen
curl -X POST http://localhost:8080/instance/create \
  -H "apikey: niles-secure-key-2026" \
  -H "Content-Type: application/json" \
  -d '{"instanceName":"niles-whatsapp","qrcode":true,"integration":"WHATSAPP-BAILEYS"}'
```

### Nachricht kommt nicht an

**1. Verbindungsstatus prüfen:**
```bash
curl -s http://localhost:8080/instance/connectionState/niles-whatsapp \
  -H "apikey: niles-secure-key-2026"

# Sollte zurückgeben: "state":"open"
# Falls "connecting" oder "close" → QR-Code neu scannen
```

**2. Nummer-Format prüfen:**
- Richtig: `4366412345678` (ohne +, ohne Leerzeichen)
- Falsch: `+43 664 123 456 78`

**3. Container-Logs prüfen:**
```bash
docker logs evolution_api | tail -50
```

### Container startet nicht / Database Error

**Fehler:** `Database provider invalid` oder `Database provider sqlite invalid`

**Ursache:** Evolution API v2.1.1 benötigt PostgreSQL (SQLite wird nicht mehr unterstützt)

**Lösung:** Docker Compose File verwenden (siehe Schritt 1) mit PostgreSQL

### "Instance not found"

**Instance-Liste abrufen:**
```bash
curl -s http://localhost:8080/instance/fetchInstances \
  -H "apikey: niles-secure-key-2026"
```

Falls Instance nicht existiert → Schritt 3 wiederholen (Instance erstellen)

### Evolution API Manager Login klappt nicht

**Prüfe:**
1. Server URL ist korrekt: `http://localhost:8080` (OHNE /manager)
2. API Key ist korrekt: `niles-secure-key-2026`
3. Evolution API Container läuft: `docker ps | grep evolution`

## Erweiterte Nutzung

### Bilder/Medien senden

```bash
curl -X POST http://localhost:8080/message/sendMedia/niles-whatsapp \
  -H "apikey: niles-secure-key-2026" \
  -H "Content-Type: application/json" \
  -d '{
    "number": "4366412345678",
    "mediatype": "image",
    "mimetype": "image/png",
    "caption": "Mein Bild",
    "media": "https://example.com/bild.png"
  }'
```

### Webhook für eingehende Nachrichten

**In n8n:**
1. Neuer Workflow: "WhatsApp Incoming"
2. **Webhook** Node:
   - HTTP Method: `POST`
   - Path: `/webhook/whatsapp`
3. Webhook-URL kopieren: `http://host.docker.internal:5678/webhook/whatsapp`

**Evolution API konfigurieren:**
```bash
curl -X POST http://localhost:8080/webhook/set/niles-whatsapp \
  -H "apikey: niles-secure-key-2026" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "http://host.docker.internal:5678/webhook/whatsapp",
    "webhook_by_events": true,
    "events": ["MESSAGES_UPSERT"]
  }'
```

**In n8n Webhook verarbeiten:**
- `{{ $json.data.key.remoteJid }}` = Absender
- `{{ $json.data.message.conversation }}` = Nachricht

## Docker Commands (Schnellreferenz)

```bash
# Status prüfen
docker ps | grep evolution

# Logs ansehen
docker logs -f evolution_api
docker logs -f evolution_postgres

# Neustart
docker compose -f docker/docker-compose.yml restart

# Stoppen
docker compose -f docker/docker-compose.yml stop

# Starten
docker compose -f docker/docker-compose.yml start

# Komplett entfernen (ACHTUNG: Daten gehen verloren!)
docker compose -f docker/docker-compose.yml down -v
```

## Ressourcen-Nutzung

| Komponente | RAM | Disk | CPU (idle) |
|------------|-----|------|------------|
| evolution_postgres | ~50 MB | ~100 MB | <1% |
| evolution_api | ~150 MB | ~200 MB | <1% |
| **Gesamt** | **~200 MB** | **~300 MB** | **<2%** |

Sehr ressourcenschonend! ✅

## Wichtige Links

- **Evolution API GitHub:** https://github.com/EvolutionAPI/evolution-api
- **Evolution API Docs:** https://doc.evolution-api.com
- **Docker Hub:** https://hub.docker.com/r/atendai/evolution-api

## Nächste Schritte

→ [Phase 6: AI Agent mit Tools](06-ai-agent.md)

Jetzt können wir WhatsApp als Tool im AI-Agenten einbinden:
- `send_whatsapp(number, message)` - Nachricht senden
- `read_whatsapp_messages(limit)` - Letzte Nachrichten abrufen (via Webhook)
