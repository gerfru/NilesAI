# Phase 4: WhatsApp Integration via Evolution API

## Übersicht

Integration von WhatsApp via Evolution API für Nachrichten-Management durch den AI-Agenten.

**Methode:** Evolution API (self-hosted, Docker) - 100% lokal

## Was ist Evolution API?

- Self-hosted WhatsApp Gateway mit REST API
- Multi-Device Support (wie WhatsApp Web)
- Web-UI für QR-Code Scanning & Session-Management
- Webhook-Support für eingehende Nachrichten
- Open Source & kostenlos

## Voraussetzungen

- Docker läuft
- n8n läuft auf Port 5678
- WhatsApp Account (mit QR-Code Zugriff)

## Schritte

### 1. Evolution API via Docker starten

```bash
# Evolution API Container
docker run -d \
  --name evolution-api \
  -p 8080:8080 \
  -v evolution_instances:/evolution/instances \
  -e AUTHENTICATION_API_KEY="DEIN_SICHERES_API_KEY" \
  --restart unless-stopped \
  atendai/evolution-api:latest

# Logs checken
docker logs evolution-api

# Status prüfen
docker ps | grep evolution
```

**WICHTIG:** `DEIN_SICHERES_API_KEY` durch ein sicheres Passwort ersetzen!

### 2. Evolution API UI öffnen

Browser: `http://localhost:8080`

**API Documentation:** `http://localhost:8080/manager`

### 3. WhatsApp Instance erstellen

**Via API (HTTP Request):**

```bash
curl -X POST http://localhost:8080/instance/create \
  -H "apikey: DEIN_SICHERES_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "instanceName": "niles-whatsapp",
    "qrcode": true,
    "integration": "WHATSAPP-BAILEYS"
  }'
```

**Response enthält:**
- `instance.instanceName`: "niles-whatsapp"
- `qrcode.base64`: QR-Code als Base64 (oder URL)

### 4. QR-Code scannen

**Option A: Via API QR-Code holen**
```bash
curl http://localhost:8080/instance/connect/niles-whatsapp \
  -H "apikey: DEIN_SICHERES_API_KEY"
```

Response enthält QR-Code als Base64 oder URL.

**Option B: Via Web-UI**
- Evolution API Manager: `http://localhost:8080/manager`
- Instance "niles-whatsapp" öffnen
- QR-Code wird angezeigt

**Mit WhatsApp-App scannen:**
1. WhatsApp öffnen
2. Einstellungen → Verknüpfte Geräte
3. "Gerät verknüpfen"
4. QR-Code scannen

### 5. Webhook für eingehende Nachrichten (optional)

**In n8n: Webhook erstellen**
1. Neuer Workflow: "WhatsApp Incoming"
2. Node: "Webhook"
3. HTTP Method: POST
4. Path: `/webhook/whatsapp`
5. Webhook-URL kopieren: `http://host.docker.internal:5678/webhook/whatsapp`

**Evolution API Webhook konfigurieren:**
```bash
curl -X POST http://localhost:8080/webhook/set/niles-whatsapp \
  -H "apikey: DEIN_SICHERES_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "http://host.docker.internal:5678/webhook/whatsapp",
    "webhook_by_events": true,
    "events": [
      "MESSAGES_UPSERT"
    ]
  }'
```

### 6. Evolution API Credential in n8n

**In n8n:**
1. Credentials → "+ Add Credential"
2. Typ: "HTTP Header Auth" (oder "Generic Credential")
3. Konfiguration:
   - Name: "Evolution API"
   - Header Name: `apikey`
   - Header Value: `DEIN_SICHERES_API_KEY`

### 7. Test-Workflow: Nachricht senden

**In n8n:**

```yaml
Workflow: "WhatsApp Nachricht senden"

Nodes:
1. Manual Trigger
2. HTTP Request
   - Method: POST
   - URL: http://host.docker.internal:8080/message/sendText/niles-whatsapp
   - Authentication: Evolution API (Header Auth)
   - Headers:
     - Content-Type: application/json
   - Body (JSON):
     {
       "number": "49xxxxxxxxxx",
       "text": "Test von Niles AI 🤖"
     }
3. Execute Workflow
```

**Format:** `number` = Ländercode + Nummer (ohne +, ohne Leerzeichen)
- Beispiel Deutschland: "491234567890"
- Beispiel Österreich: "43664xxxxxxx"

### 8. Test-Workflow: Nachrichten empfangen

**In n8n:**

```yaml
Workflow: "WhatsApp Incoming Messages"

Nodes:
1. Webhook Trigger
   - Path: /webhook/whatsapp
2. Filter (nur neue Nachrichten)
   - {{ $json.event }} = "messages.upsert"
3. Extract Data
   - Sender: {{ $json.data.key.remoteJid }}
   - Message: {{ $json.data.message.conversation }}
4. LLM Node (AI Antwort generieren)
5. HTTP Request (Antwort senden)
   - URL: http://host.docker.internal:8080/message/sendText/niles-whatsapp
   - Body: { "number": "{{ sender }}", "text": "{{ ai_response }}" }
```

## Wichtige API-Endpunkte

| Endpunkt | Methode | Beschreibung |
|----------|---------|--------------|
| `/instance/create` | POST | Instance erstellen |
| `/instance/connect/{instance}` | GET | QR-Code holen |
| `/instance/connectionState/{instance}` | GET | Verbindungsstatus |
| `/message/sendText/{instance}` | POST | Textnachricht senden |
| `/message/sendMedia/{instance}` | POST | Bild/Video senden |
| `/webhook/set/{instance}` | POST | Webhook konfigurieren |

**Full API Docs:** http://localhost:8080/manager

## Wichtige Dateien & Volumes

- **Docker Volume:** `evolution_instances` - Session-Daten
- **API Key:** Im Docker ENV oder `.env` Datei

## Verifikation

- [ ] Evolution API Container läuft auf Port 8080
- [ ] WhatsApp Instance "niles-whatsapp" erstellt
- [ ] QR-Code gescannt, Verbindung aktiv
- [ ] Test-Nachricht erfolgreich gesendet
- [ ] Webhook konfiguriert (optional)
- [ ] Eingehende Nachrichten in n8n empfangen

## Troubleshooting

### QR-Code expired / Verbindung verloren

**Neuverbindung:**
```bash
# QR-Code neu generieren
curl http://localhost:8080/instance/connect/niles-whatsapp \
  -H "apikey: DEIN_SICHERES_API_KEY"

# Erneut mit WhatsApp-App scannen
```

### "Instance not found"

**Instance-Status prüfen:**
```bash
curl http://localhost:8080/instance/fetchInstances \
  -H "apikey: DEIN_SICHERES_API_KEY"
```

Falls nicht vorhanden → Schritt 3 wiederholen (Instance erstellen)

### Nachrichten kommen nicht an

1. **Nummer-Format prüfen:**
   - Richtig: "491234567890" (ohne +, ohne Leerzeichen)
   - Falsch: "+49 123 456 7890"

2. **Connection State prüfen:**
```bash
curl http://localhost:8080/instance/connectionState/niles-whatsapp \
  -H "apikey: DEIN_SICHERES_API_KEY"
```

Sollte `"state": "open"` zurückgeben.

### WhatsApp Account gebannt / Rate Limit

**WhatsApp Best Practices:**
- Nicht zu viele Nachrichten auf einmal senden
- Nur an Kontakte die dich gespeichert haben
- Nicht spammen (wird als Missbrauch erkannt)
- Business API für kommerzielle Nutzung verwenden

**Bei Ban:**
- Evolution API nutzt Multi-Device Protocol (wie WhatsApp Web)
- Ban ist selten bei normaler Nutzung
- Alternative: WhatsApp Business API (offiziell, kostenpflichtig)

## Alternativen & Weiterführende Links

### Offizielle WhatsApp Business API

Falls Evolution API nicht ausreicht oder für kommerzielle Nutzung gibt es die offizielle WhatsApp Business API:

**Vorteile:**
- Offiziell von Meta/WhatsApp
- Kein Ban-Risiko
- Verified Business Account
- Higher Rate Limits

**Nachteile:**
- Kostenpflichtig (~$0.005-0.10 pro Nachricht)
- Komplexere Einrichtung
- Cloud-Abhängigkeit (nicht 100% lokal)

### Evolution API Dokumentation

- **GitHub:** https://github.com/EvolutionAPI/evolution-api
- **Docs:** https://doc.evolution-api.com/
- **Docker Hub:** https://hub.docker.com/r/atendai/evolution-api

## Docker Commands (Schnellreferenz)

```bash
# Status prüfen
docker ps | grep evolution

# Logs ansehen
docker logs -f evolution-api

# Neustart
docker restart evolution-api

# Stoppen
docker stop evolution-api

# Container entfernen (Daten bleiben in Volume!)
docker rm evolution-api

# Volume-Daten löschen (ACHTUNG: Sessions gehen verloren!)
docker volume rm evolution_instances
```

## Nächste Schritte

→ [Phase 5: AI Agent mit Tools](05-ai-agent.md)

Jetzt können wir WhatsApp als Tool im AI-Agenten einbinden:
- `send_whatsapp(number, message)` - Nachricht senden
- `read_whatsapp_messages(limit)` - Letzte Nachrichten abrufen
