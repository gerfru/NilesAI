# Niles AI Core -- API Reference

> **Stand:** 2026-02-17

---

## Authentifizierung

### /chat -- API Key

Erwartet den Header `X-API-Key` mit dem Wert von `NILES_API_KEY`. Wird kein Key gesetzt, generiert Niles beim Start einen zufaelligen Key und loggt ihn.

```bash
curl -X POST http://localhost:8000/chat \
  -H "X-API-Key: <NILES_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"message": "Hallo"}'
```

### /webhook/whatsapp -- URL Token

Erwartet den Query-Parameter `?token=` mit dem Wert von `EVOLUTION_API_KEY`. Evolution API (self-hosted) kann keine Custom-Headers bei Webhook-Requests senden, daher wird ein URL-Token verwendet.

```
POST /webhook/whatsapp?token=<EVOLUTION_API_KEY>
```

### /health -- Kein Auth

Health Check ist oeffentlich zugaenglich.

---

## Endpoints

### GET /health

Health Check. Gibt den Status des Servers zurueck.

**Response:**

```json
{"status": "ok"}
```

**Status Codes:**

| Code | Bedeutung |
|------|-----------|
| 200 | Server laeuft |

---

### POST /chat

Direkte Chat-Schnittstelle fuer Tests und Integrationen. Verarbeitet die Nachricht ueber den Agent (inkl. Tool-Calls, Memory, History) und gibt die Antwort zurueck.

**Request:**

```json
{
  "message": "Wie heisst der Bundeskanzler?"
}
```

| Feld | Typ | Pflicht | Beschreibung |
|------|-----|---------|-------------|
| `message` | string | Ja | Nachrichtentext |

**Response:**

```json
{
  "response": "Der aktuelle Bundeskanzler ist ..."
}
```

| Feld | Typ | Beschreibung |
|------|-----|-------------|
| `response` | string | Agent-Antwort |

**Status Codes:**

| Code | Bedeutung |
|------|-----------|
| 200 | Nachricht verarbeitet |
| 401 | Fehlender oder ungueltiger API Key |
| 422 | Ungueltige Request-Daten |
| 500 | Interner Fehler |

**Hinweise:**

- Erfordert `X-API-Key` Header (siehe Authentifizierung)
- Verwendet `chat_id = "api"` fuer die Konversations-Historie
- Memory und Tool-Calls sind voll verfuegbar (gleiche Pipeline wie WhatsApp)

**Beispiel:**

```bash
curl -X POST http://localhost:8000/chat \
  -H "X-API-Key: <NILES_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"message": "Merke dir: Mein Lieblingsessen ist Pizza"}'
```

---

### POST /webhook/whatsapp

Webhook-Endpoint fuer die Evolution API. Empfaengt WhatsApp-Events und verarbeitet eingehende Nachrichten.

**Request:**

Evolution API v2.3.7 Payload (Beispiel fuer `messages.upsert`):

```json
{
  "event": "messages.upsert",
  "instance": "niles-whatsapp",
  "data": {
    "key": {
      "remoteJid": "436601234567@s.whatsapp.net",
      "fromMe": false,
      "id": "3EB0A..."
    },
    "pushName": "Max",
    "message": {
      "conversation": "Hallo Niles!"
    },
    "messageType": "conversation",
    "messageTimestamp": 1708000000
  }
}
```

**Verarbeitungslogik:**

1. Nur `event == "messages.upsert"` wird verarbeitet, alles andere ignoriert
2. Eigene Nachrichten (`fromMe: true`) werden ignoriert
3. Text wird aus `message.conversation` oder `message.extendedTextMessage.text` extrahiert
4. Nachrichten ohne Textinhalt werden ignoriert
5. Telefonnummer wird aus der JID extrahiert (`@s.whatsapp.net` abgeschnitten)
6. Event wird an `NilesAgent.process_event()` uebergeben
7. Antwort wird via `WhatsAppAction.send_message()` zurueckgesendet

**Authentifizierung:**

Erfordert `?token=<EVOLUTION_API_KEY>` als Query-Parameter (siehe Authentifizierung). Gibt HTTP 401 bei ungueltigem oder fehlendem Token zurueck.

**Response:**

Bei gueltigem Token: Gibt immer HTTP 200 zurueck, unabhaengig vom Verarbeitungsergebnis. Dies verhindert Retry-Spam durch die Evolution API.

```json
{"status": "processed"}
```

oder bei ignorierten Events:

```json
{"status": "ignored", "reason": "event type: connection.update"}
```

---

## Agent Tools

Der Agent kann ueber LLM Tool-Calls folgende Funktionen ausfuehren:

### find_contact

Sucht einen Kontakt nach Name in der PostgreSQL-Datenbank.

**Parameter:**

| Name | Typ | Pflicht | Beschreibung |
|------|-----|---------|-------------|
| `name` | string | Ja | Name oder Namensteil |

**Return (Erfolg):**

```json
{
  "full_name": "Max Mustermann",
  "phone": "436601234567",
  "email": "max@example.com"
}
```

**Return (Fehler):**

```json
{"error": "Kontakt 'Maxl' nicht gefunden"}
```

**Suchpriorisierung:** exakt > prefix > partial > first/last name.

---

### send_whatsapp

Sendet eine WhatsApp-Nachricht. Akzeptiert Telefonnummern oder Kontaktnamen (wird automatisch aufgeloest).

**Parameter:**

| Name | Typ | Pflicht | Beschreibung |
|------|-----|---------|-------------|
| `to` | string | Ja | Telefonnummer (z.B. `"436601234567"`) oder Kontaktname |
| `text` | string | Ja | Nachrichtentext |

**Return (Erfolg):**

```json
{"status": "sent", "to": "436601234567"}
```

**Return (Fehler):**

```json
{"error": "Kontakt 'Unbekannt' nicht gefunden oder keine Telefonnummer vorhanden"}
```

**Hinweise:**

- Wenn `to` keine Zahl ist, wird zuerst `find_contact` ausgefuehrt
- Telefonnummern werden automatisch in JID-Format konvertiert (`@s.whatsapp.net`)
- Timeout: 30 Sekunden

---

### remember

Speichert einen Fakt dauerhaft im Key-Value Memory. UPSERT-Semantik: existierende Keys werden ueberschrieben.

**Parameter:**

| Name | Typ | Pflicht | Beschreibung |
|------|-----|---------|-------------|
| `key` | string | Ja | Kurzer Schluessel (z.B. `"zahnarzt_termin"`) |
| `value` | string | Ja | Zu merkender Inhalt |

**Return:**

```json
{"status": "saved", "key": "zahnarzt_termin"}
```

---

### recall

Ruft einen gespeicherten Fakt aus dem Memory ab.

**Parameter:**

| Name | Typ | Pflicht | Beschreibung |
|------|-----|---------|-------------|
| `key` | string | Ja | Schluessel |

**Return (Erfolg):**

```json
{"key": "zahnarzt_termin", "value": "Morgen um 10 Uhr"}
```

**Return (Fehler):**

```json
{"error": "Nichts gespeichert unter 'unbekannt'"}
```

**Hinweis:** Alle Memory-Eintraege werden automatisch in den System Prompt injiziert. `recall` ist nur noetig, wenn der Agent gezielt nach einem bestimmten Key suchen will.

---

## Evolution API Webhook-Konfiguration

Die Evolution API muss so konfiguriert werden, dass sie Webhooks an Niles sendet:

```bash
curl -X POST http://localhost:8080/webhook/set/niles-whatsapp \
  -H "apikey: <EVOLUTION_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{
    "webhook": {
      "enabled": true,
      "url": "http://niles_core:8000/webhook/whatsapp?token=<EVOLUTION_API_KEY>",
      "events": ["MESSAGES_UPSERT"]
    }
  }'
```

Die Webhook-URL verwendet den Docker-internen Hostnamen `niles_core`.

---

## Fehlerbehandlung

| Szenario | Verhalten |
|----------|-----------|
| LLM nicht erreichbar | Fehlermeldung an User, Fehler geloggt |
| LLM gibt leere Antwort | Warning geloggt, leerer String zurueckgegeben |
| Tool-Call mit ungueltigen Argumenten | `{"error": "Invalid arguments"}` zurueck an LLM |
| Unbekannter Tool-Name | `{"error": "Unknown tool: ..."}` zurueck an LLM |
| Max Tool-Runden erreicht (5) | Warning geloggt, Fallback-Nachricht an User |
| Webhook: ungueltiges JSON | Warning geloggt, HTTP 200 |
| Webhook: Agent-Fehler | Exception geloggt, HTTP 200 (kein Retry) |
| WhatsApp senden fehlgeschlagen | Fehler geloggt, `{"error": "..."}` zurueck an LLM |

---

## Weitere Dokumentation

- [Technische Spezifikation](Niles-Core-Spec.md) -- Komponentenbeschreibung und Roadmap
- [Architektur](Architecture.md) -- Systemuebersicht, Module, Datenfluss
- [Development Guide](Development.md) -- Setup, Testing, Konventionen
