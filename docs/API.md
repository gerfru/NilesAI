# Niles AI Core -- API Reference

> **Stand:** 2026-02-23

---

## HTTPS (Caddy Reverse Proxy)

Alle externen Zugriffe laufen ueber HTTPS via Caddy Reverse Proxy mit self-signed Zertifikaten (`tls internal`).

| Port | Service | Intern |
| ---- | ------- | ------ |
| 443 | Niles Core API + Web-UI | niles_core:8000 |
| 8443 | Evolution API | evolution_api:8080 |

- **Self-signed Zertifikate:** Browser-Warnung beim ersten Zugriff akzeptieren
- **curl:** `--insecure` Flag verwenden (oder `-k`)
- **Interner Docker-Traffic:** bleibt HTTP (Container-zu-Container)

---

## Authentifizierung

### /chat -- API Key

Erwartet den Header `X-API-Key` mit dem Wert von `NILES_API_KEY`. Wird kein Key gesetzt, generiert Niles beim Start einen zufaelligen Key (abrufbar via `docker exec niles_core printenv NILES_API_KEY`).

```bash
curl -k -X POST https://localhost/chat \
  -H "X-API-Key: <NILES_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"message": "Hallo"}'
```

### /webhook/whatsapp -- URL Token

Erwartet den Query-Parameter `?token=` mit dem Wert von `EVOLUTION_API_KEY`. Evolution API (self-hosted v2.3.x) kann keine Custom-Headers bei Webhook-Requests senden (Feature-Request: [EvolutionAPI/evolution-api#1933](https://github.com/EvolutionAPI/evolution-api/issues/1933)), daher wird ein URL-Token verwendet.

```text
POST /webhook/whatsapp?token=<EVOLUTION_API_KEY>
```

**Risikobewertung:** Query-Parameter koennen in Server-Logs erscheinen. Caddy loggt standardmaessig keine Query-Parameter. Der Webhook-Traffic laeuft intern ueber das Docker-Netzwerk (HTTP, Container-zu-Container), nie ueber das oeffentliche Netz. Sobald Evolution API Custom-Headers unterstuetzt, sollte auf Header-basierte Authentifizierung migriert werden.

### /ui/* -- Session Cookies (Google OAuth oder API-Key)

Die Web-UI verwendet signierte Session-Cookies (itsdangerous). Login ueber zwei Wege:

1. **Google OAuth 2.0** (primaer, wenn `GOOGLE_CLIENT_ID` + `GOOGLE_CLIENT_SECRET` konfiguriert)
2. **API-Key** (Fallback, wenn kein Google OAuth konfiguriert)

Session-Cookies werden mit `SESSION_SECRET` signiert (nicht `NILES_API_KEY`). Alle POST-Endpoints erfordern zusaetzlich ein CSRF-Token (Double-Submit Pattern: `niles_csrf` Cookie + `X-CSRF-Token` Header).

### /health -- Kein Auth

Health Check ist oeffentlich zugaenglich. Rate Limiting (60 req/min) gilt nicht fuer `/health`.

### Rate Limiting

Alle Endpoints (ausser `/health` und `/static`) sind auf 60 Requests pro Minute pro Client-IP begrenzt. Bei Ueberschreitung wird HTTP 429 zurueckgegeben.

API-Key Login (`POST /ui/login`) hat zusaetzlich ein eigenes Limit: max 5 Versuche pro IP in 5 Minuten.

### Secrets Rotation

Keys koennen jederzeit rotiert werden:

1. Neuen Key in `.env` setzen (`NILES_API_KEY`, `SESSION_SECRET`, `EVOLUTION_API_KEY`)
2. Container neu starten: `./scripts/start.sh`
3. Bei Aenderung von `EVOLUTION_API_KEY`: Webhook-URL in der Evolution API aktualisieren (siehe unten)
4. Bei Aenderung von `SESSION_SECRET`: Alle bestehenden Web-UI Sessions werden ungueltig (Benutzer muessen sich erneut einloggen)

Wird `NILES_API_KEY` oder `SESSION_SECRET` nicht gesetzt, generiert Niles bei jedem Containerstart einen neuen Key (automatische Rotation).

---

## API Endpoints

### GET /health

Health Check. Gibt den Status des Servers und DB-Pool-Info zurueck.

**Response:**

```json
{
  "status": "ok",
  "db_pool": {"size": 2, "free": 2, "min": 2, "max": 10}
}
```

---

### POST /chat

Direkte Chat-Schnittstelle fuer Tests und Integrationen. Verarbeitet die Nachricht ueber den Agent (inkl. Tool-Calls, Memory, History) und gibt die Antwort zurueck.

**Request:**

```json
{
  "message": "Wie heisst der Bundeskanzler?"
}
```

**Response:**

```json
{
  "response": "Der aktuelle Bundeskanzler ist ..."
}
```

**Status Codes:**

| Code | Bedeutung |
| ---- | --------- |
| 200 | Nachricht verarbeitet |
| 401 | Fehlender oder ungueltiger API Key |
| 422 | Ungueltige Request-Daten |
| 500 | Interner Fehler |

**Hinweise:**

- Erfordert `X-API-Key` Header (siehe Authentifizierung)
- Verwendet `chat_id = "api"` fuer die Konversations-Historie
- Memory und Tool-Calls sind voll verfuegbar (gleiche Pipeline wie WhatsApp)

---

### POST /webhook/whatsapp

Webhook-Endpoint fuer die Evolution API. Empfaengt WhatsApp-Events und verarbeitet eingehende Nachrichten.

**Verarbeitungslogik:**

1. Nur `event == "messages.upsert"` wird verarbeitet, alles andere ignoriert
2. Eigene Nachrichten (`fromMe: true`) werden ignoriert
3. Text wird aus `message.conversation` oder `message.extendedTextMessage.text` extrahiert
4. Nachrichten ohne Textinhalt werden ignoriert
5. Telefonnummer wird aus der JID extrahiert (`@s.whatsapp.net` abgeschnitten)
6. Event wird an `NilesAgent.process_event()` uebergeben
7. Antwort wird via `WhatsAppAction.send_message()` zurueckgesendet

**Authentifizierung:** Erfordert `?token=<EVOLUTION_API_KEY>` als Query-Parameter. HTTP 401 bei ungueltigem Token.

**Response:** Gibt immer HTTP 200 zurueck (verhindert Retry-Spam durch die Evolution API).

---

## Web-UI Endpoints (`/ui/*`)

Alle `/ui/*` Routen verwenden signierte Session-Cookies. Nicht-eingeloggte Benutzer werden auf `/ui/login` umgeleitet.

### GET /ui/login

Login-Seite. Zeigt je nach Konfiguration:

- **Google OAuth konfiguriert:** "Mit Google anmelden"-Button + API-Key als ausklappbarer Fallback
- **Kein Google OAuth:** API-Key Eingabefeld als primaerer Login

### POST /ui/login

API-Key Login (Fallback). Erwartet `api_key` als Form-Feld. Erstellt bei Erfolg eine lokale Admin-Session (`uid=0`).

**Status Codes:** 303 (Redirect bei Erfolg), 401 (falscher Key), 429 (Rate Limit)

### GET /ui/login/google

Leitet zum Google OAuth Consent Screen weiter. Setzt `oauth_state` Cookie fuer CSRF-Schutz.

### GET /ui/callback/google

Google OAuth Callback. Tauscht Authorization-Code gegen Access-Token, ruft Userinfo ab, prueft:

1. State-Parameter (CSRF)
2. `email_verified` (nur verifizierte Accounts)
3. `GOOGLE_ALLOWED_EMAILS` Whitelist (wenn konfiguriert)

Erstellt oder aktualisiert User in DB, setzt Session-Cookie.

**Fehlerbehandlung:** OAuth-Fehlercodes werden auf sichere deutsche Meldungen gemappt (kein Reflection von Fehlerparametern).

### POST /ui/logout

Loescht Session-, CSRF- und OAuth-State-Cookies. POST (nicht GET) um Logout-CSRF zu verhindern.

- **htmx-Requests:** Gibt `HX-Redirect: /ui/login` Header zurueck
- **Regulaere Requests:** HTTP 303 Redirect

### GET /ui/chat

Chat-Seite mit per-User Konversations-Historie. Zeigt die letzten 20 Nachrichten (paginiert).

### GET /ui/settings

Settings-Dashboard. Zeigt Feature-Flags, Text-Settings und Infrastruktur-Settings (Passwoerter maskiert).

### GET /ui/api/chat/history

Laed aeltere Chat-Nachrichten (Pagination). Query-Parameter: `offset` (default: 0).

Gibt ein HTML-Fragment (htmx) zurueck.

### POST /ui/api/chat/stream

Sendet eine Chat-Nachricht und streamt die Antwort via SSE (Server-Sent Events). Erwartet `message` als Form-Feld + CSRF-Token.

**Ablauf:**

1. User-Nachricht wird sofort im Browser als Chat-Bubble angezeigt (client-seitig, kein Server-Roundtrip)
2. SSE-Stream liefert Events:
   - `{"type": "status", "text": "find_contact..."}` -- Tool-Call laeuft
   - `{"type": "chunk", "text": "partial text"}` -- Antwort-Text (Wort fuer Wort)
   - `{"type": "done"}` -- Stream beendet
3. Markdown wird nach Abschluss client-seitig gerendert (marked.js + DOMPurify)

**Validierung:** Nachrichten ueber 2000 Zeichen werden mit HTTP 400 abgelehnt.

**Response:** `Content-Type: text/event-stream` mit `X-Accel-Buffering: no` Header.

### POST /ui/api/chat

Fallback-Endpoint (nicht-streaming). Sendet eine Chat-Nachricht. Erwartet `message` als Form-Feld + CSRF-Token.

Verarbeitet die Nachricht ueber den Agent (gleiche Pipeline wie `/chat` und WhatsApp). Gibt HTML-Fragment mit User- und Assistant-Nachricht zurueck.

### POST /ui/api/chat/clear

Loescht die Chat-Historie des aktuellen Users. Erfordert CSRF-Token.

### GET /ui/api/calendar/sources

Gibt die Liste aller konfigurierten Kalenderquellen als HTML-Fragment (htmx) zurueck. Zeigt Name, URL, Typ-Badge (ICS/CalDAV/Google), Sync-Status und Fehler.

### POST /ui/api/calendar/sources

Fuegt eine neue Kalenderquelle hinzu. Erwartet Form-Felder: `source_type` (ics/caldav), `name`, `url`, optional `auth_user`, `auth_password`. Google-Kalender werden nicht ueber dieses Formular hinzugefuegt, sondern ueber den OAuth-Flow (siehe unten). Gibt die aktualisierte Quellenliste als HTML-Fragment zurueck.

**Validierung:** Nur HTTPS-URLs, max 2048 Zeichen URL, max 200 Zeichen Name.

### DELETE /ui/api/calendar/sources/{source_id}

Entfernt eine Kalenderquelle. Events der Quelle werden via CASCADE automatisch geloescht. Gibt die aktualisierte Quellenliste als HTML-Fragment zurueck.

### POST /ui/api/calendar/sources/{source_id}/sync

Triggert einen manuellen Sync fuer eine einzelne Kalenderquelle. Gibt die aktualisierte Quellenliste als HTML-Fragment zurueck.

### GET /ui/api/calendar/google/connect

Leitet zu Google OAuth mit Calendar-Scope weiter (erfordert Login-Session). Setzt einen `gcal_oauth_state`-Cookie fuer CSRF-Schutz. Nur sichtbar wenn `GOOGLE_CLIENT_ID` und `GOOGLE_CLIENT_SECRET` konfiguriert sind.

### GET /ui/callback/google/calendar

Google OAuth Callback fuer Calendar-Verbindung. Tauscht Authorization-Code gegen Access+Refresh-Token, entdeckt alle Kalender via Google Calendar REST API und erstellt automatisch `calendar_sources`-Eintraege (owner/writer als beschreibbar, reader als nur-lesen). Triggert initialen Sync im Hintergrund. Redirect-URI muss in der Google Cloud Console registriert sein: `https://<HOST>/ui/callback/google/calendar`.

### POST /ui/api/settings/{key}

Aendert eine einzelne Runtime-Einstellung. Erwartet `value` als Form-Feld + CSRF-Token.

- Nur Keys in `EDITABLE_SETTINGS` sind erlaubt (Feature-Flags, LLM-Config, Timezone, Log-Level, CardDAV-Credentials)
- Unbekannte Keys werden mit Fehlermeldung abgelehnt
- Aenderungen werden in `settings_overrides` Tabelle persistiert

### GET /ui/api/whatsapp/status

Gibt den WhatsApp-Verbindungsstatus des aktuellen Users als HTML-Fragment zurueck. Zeigt verbundene Telefonnummer, QR-Code (wenn connecting), oder Verbindungs-Button.

### POST /ui/api/whatsapp/connect

Erstellt eine neue Evolution API Instance fuer den aktuellen User und gibt den QR-Code zur WhatsApp-Verknuepfung zurueck. Instance-Name: `niles-wa-{user_id}`. Webhook wird automatisch konfiguriert.

### POST /ui/api/whatsapp/disconnect

Trennt die WhatsApp-Verbindung des aktuellen Users. Fuehrt Logout und Delete der Evolution API Instance durch und entfernt die Session aus der DB.

### GET /ui/api/contacts/status

Gibt den CardDAV-Verbindungsstatus als HTML-Fragment zurueck. Zeigt Anzahl synchronisierter Kontakte und letzte Sync-Zeit.

### POST /ui/api/contacts/connect

Testet CardDAV-Verbindung mit den uebergebenen Credentials (`url`, `username`, `password`). Bei Erfolg: Credentials in Settings-Store speichern, initialen Sync starten und taeglichen Sync-Job registrieren.

### POST /ui/api/contacts/disconnect

Entfernt CardDAV-Credentials aus dem Settings-Store, loescht alle synchronisierten Kontakte und entfernt den Sync-Job.

### POST /ui/api/contacts/sync

Triggert einen manuellen CardDAV-Kontakt-Sync. Gibt den aktualisierten Status als HTML-Fragment zurueck.

### GET /ui/api/caldav/calendars

Gibt die verfuegbaren CalDAV-Kalender-Collections als HTML-Fragment zurueck (via PROPFIND Discovery).

---

## Agent Tools

Der Agent kann ueber LLM Tool-Calls folgende Funktionen ausfuehren:

### find_contact

Sucht einen Kontakt nach Name in der PostgreSQL-Datenbank. Unterstuetzt Multi-Word-Suche (z.B. "Thomas Brunner" matcht auch "Brunner Thomas").

**Parameter:**

| Name | Typ | Pflicht | Beschreibung |
| ---- | --- | ------- | ------------ |
| `name` | string | Ja | Name oder Namensteil (ein- oder mehrwortig) |

**Return (Erfolg):**

```json
{
  "full_name": "Max Mustermann",
  "phone": "436601234567",
  "phones": [
    {"type": "mobile", "number": "436601234567"},
    {"type": "work", "number": "4312345678"}
  ],
  "email": "max@example.com"
}
```

**Return (Fehler):**

```json
{"error": "Kontakt 'Maxl' nicht gefunden"}
```

**Suchpriorisierung:** exakt > prefix > partial > multi-word across name fields.

---

### send_whatsapp

Sendet eine WhatsApp-Nachricht. Akzeptiert Telefonnummern oder Kontaktnamen (wird automatisch aufgeloest).

**Parameter:**

| Name | Typ | Pflicht | Beschreibung |
| ---- | --- | ------- | ------------ |
| `to` | string | Ja | Telefonnummer (z.B. `"436601234567"`) oder Kontaktname |
| `text` | string | Ja | Nachrichtentext |

**Return (Erfolg):**

```json
{"status": "sent", "to": "436601234567"}
```

**Hinweise:**

- Wenn `to` keine Zahl ist, wird zuerst `find_contact` ausgefuehrt
- **Multi-Phone:** Hat der Kontakt mehrere Nummern, wird der User nach einer Auswahl gefragt (nummerierte Liste, 5 min TTL). Diese Auswahl umgeht das LLM komplett (Bypass-Flow).
- Telefonnummern werden automatisch in JID-Format konvertiert (`@s.whatsapp.net`)
- **Per-User Instance:** Bei Web-UI Users wird die per-User WhatsApp Instance verwendet (Fallback: globale Instance)
- Timeout: 30 Sekunden

---

### remember

Speichert einen Fakt dauerhaft im Key-Value Memory. UPSERT-Semantik: existierende Keys werden ueberschrieben.

**Parameter:**

| Name | Typ | Pflicht | Beschreibung |
| ---- | --- | ------- | ------------ |
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
| ---- | --- | ------- | ------------ |
| `key` | string | Ja | Schluessel |

**Return (Erfolg):**

```json
{"key": "zahnarzt_termin", "value": "Morgen um 10 Uhr"}
```

**Hinweis:** Alle Memory-Eintraege werden automatisch in den System Prompt injiziert. `recall` ist nur noetig, wenn der Agent gezielt nach einem bestimmten Key suchen will.

---

### find_event

Sucht Kalender-Events aus allen konfigurierten Kalenderquellen (ICS, CalDAV, Google). Max 10 Ergebnisse, sortiert nach Startzeit.

**Parameter:**

| Name | Typ | Pflicht | Beschreibung |
| ---- | --- | ------- | ------------ |
| `query` | string | Nein | Suchbegriff (Name, Ort, Beschreibung). Leer fuer reine Datumssuche. |
| `date_from` | string | Nein | Startdatum (ISO-Format, z.B. `"2026-02-20"`). |
| `date_to` | string | Nein | Enddatum (ISO-Format). Nur bei expliziten Zeitraeumen. |
| `calendar` | string | Nein | Name des Kalenders fuer gezielte Suche. |

**Return (Erfolg):**

```json
{"events": [...], "count": 3}
```

Jedes Event-Objekt enthaelt:

| Feld | Typ | Immer | Beschreibung |
| ---- | --- | ----- | ------------ |
| `summary` | string | Ja | Titel des Termins |
| `start` | string | Ja | Startzeit (ISO) oder Datum bei Ganztags-Events |
| `all_day` | boolean | Ja | `true` fuer ganztaegige Termine |
| `end` | string | Nein | Endzeit (ISO), nur wenn vorhanden |
| `description` | string | Nein | Beschreibung, nur wenn vorhanden |
| `location` | string | Nein | Ort, nur wenn vorhanden |
| `status` | string | Nein | `"verfuegbar"` wenn der Termin die Zeit nicht blockiert (iCal `TRANSP:TRANSPARENT`). Fehlt bei normalen (blockierenden) Terminen. |

**Return (Fehler):**

```json
{"error": "Keine Termine gefunden"}
```

---

### create_event

Erstellt einen neuen Kalender-Eintrag auf der ersten beschreibbaren Kalenderquelle (via `CalendarSourceManager`). Gibt einen Fehler zurueck wenn keine beschreibbare Quelle konfiguriert ist.

**Parameter:**

| Name | Typ | Pflicht | Beschreibung |
| ---- | --- | ------- | ------------ |
| `summary` | string | Ja | Titel des Events |
| `start` | string | Ja | Startzeit (ISO-Format, z.B. `"2026-02-20T14:00"`) |
| `end` | string | Nein | Endzeit (ISO-Format). Standard: 1 Stunde nach Start. |
| `description` | string | Nein | Beschreibung des Termins |
| `location` | string | Nein | Ort des Termins |

---

### list_tasks

Listet offene Aufgaben aus Vikunja. Nur verfuegbar wenn `feature_vikunja` aktiv ist.

**Parameter:**

| Name | Typ | Pflicht | Beschreibung |
| ---- | --- | ------- | ------------ |
| `project` | string | Nein | Projektname zum Filtern. Leer = alle Projekte. |
| `include_done` | boolean | Nein | Auch erledigte Aufgaben anzeigen. Standard: false. |

**Return (Erfolg):**

```json
{"tasks": [{"id": 1, "title": "Milch kaufen", "done": false, "due_date": "2026-02-25T18:00:00Z"}], "count": 1}
```

**Return (Fehler):**

```json
{"error": "Keine Aufgaben gefunden"}
```

---

### create_task

Erstellt eine neue Aufgabe in Vikunja. Nur verfuegbar wenn `feature_vikunja` aktiv ist.

**Parameter:**

| Name | Typ | Pflicht | Beschreibung |
| ---- | --- | ------- | ------------ |
| `title` | string | Ja | Titel der Aufgabe |
| `description` | string | Nein | Beschreibung der Aufgabe |
| `due_date` | string | Nein | Faelligkeitsdatum (ISO-Format, z.B. `"2026-02-25T18:00"`) |
| `priority` | integer | Nein | Prioritaet: 0=keine, 1=niedrig, 2=mittel, 3=hoch, 4=dringend. Standard: 0. |
| `project` | string | Nein | Projektname. Leer = Standard-Projekt. |

**Return (Erfolg):**

```json
{"created": true, "id": 20, "title": "Zahnarzt anrufen", "project_id": 1}
```

**Return (Fehler):**

```json
{"error": "Projekt 'Nonexistent' nicht gefunden"}
```

---

### complete_task

Markiert eine Aufgabe als erledigt. Sucht nach dem Titel in offenen Aufgaben. Nur verfuegbar wenn `feature_vikunja` aktiv ist.

**Parameter:**

| Name | Typ | Pflicht | Beschreibung |
| ---- | --- | ------- | ------------ |
| `title` | string | Ja | Titel oder Teil des Titels der Aufgabe |

**Return (Erfolg):**

```json
{"completed": true, "title": "Milch kaufen"}
```

**Return (Fehler -- nicht gefunden):**

```json
{"error": "Keine offene Aufgabe gefunden: 'Nonexistent'"}
```

**Return (Fehler -- mehrdeutig):**

```json
{"error": "Mehrere Aufgaben gefunden. Welche meinst du?", "matches": ["Einkaufen", "Email schreiben"]}
```

---

## Evolution API Webhook-Konfiguration

Die Evolution API muss so konfiguriert werden, dass sie Webhooks an Niles sendet:

```bash
curl -k -X POST https://localhost:8443/webhook/set/niles-whatsapp \
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

**Hinweis:** Die Webhook-URL nutzt den Docker-internen Hostnamen `niles_core` (HTTP, Container-zu-Container). Der `curl`-Aufruf selbst geht ueber Caddy (HTTPS).

---

## Fehlerbehandlung

| Szenario | Verhalten |
| -------- | --------- |
| LLM nicht erreichbar | Fehlermeldung an User, Fehler geloggt |
| LLM gibt leere Antwort | Warning geloggt, leerer String zurueckgegeben |
| Tool-Call mit ungueltigen Argumenten | `{"error": "Invalid arguments"}` zurueck an LLM |
| Unbekannter Tool-Name | `{"error": "Unknown tool: ..."}` zurueck an LLM |
| Max Tool-Runden erreicht (5) | Warning geloggt, Fallback-Nachricht an User |
| Webhook: ungueltiges JSON | Warning geloggt, HTTP 200 |
| Webhook: Agent-Fehler | Exception geloggt, HTTP 200 (kein Retry) |
| WhatsApp senden fehlgeschlagen | Fehler geloggt, `{"error": "..."}` zurueck an LLM |
| Web-UI: Session ungueltig | Redirect zu /ui/login |
| Web-UI: CSRF ungueltig | 403, Redirect zu /ui/login (via HX-Redirect) |
| Web-UI: Agent-Fehler | Fehlermeldung im Chat-Fragment angezeigt |
| Web-UI: SSE Stream-Fehler | Fehlermeldung als Assistant-Bubble angezeigt |
| Web-UI: Nachricht zu lang (>2000) | HTTP 400, Nachricht nicht gesendet |

---

## Weitere Dokumentation

- [Technische Spezifikation](Niles-Core-Spec.md) -- Architektur, Komponenten, Konfiguration, Roadmap
- [Development Guide](Development.md) -- Setup, Testing, Konventionen
