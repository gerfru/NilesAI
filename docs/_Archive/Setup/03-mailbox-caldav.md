# Phase 3b: mailbox.org CalDAV Integration

## Übersicht

Integration von mailbox.org Kalender in n8n via CalDAV für lokales Kalender-Management durch den AI-Agenten.

**Vorteile gegenüber Google Calendar:**
- ✅ DSGVO-konform (deutscher Provider)
- ✅ Keine OAuth-Komplexität (Basic Auth)
- ✅ Kein "Erweitertes Sicherheitsprogramm" Problem
- ✅ Funktioniert mit Thunderbird, iOS, Android

## Voraussetzungen

- n8n läuft auf Port 5678
- mailbox.org Account mit aktiviertem CalDAV
- CalDAV-URL aus mailbox.org Kalender-Einstellungen

## Schritte

### 1. CalDAV-URL von mailbox.org abrufen

**In mailbox.org Web-Interface:**
1. Kalender öffnen
2. Kalender auswählen → Rechtsklick → **"Eigenschaften"**
3. **CalDAV-URL kopieren:**
   ```
   https://dav.mailbox.org/caldav/Y2FsOi8vMC8zMQ
   ```

**URL-Format:** `https://dav.mailbox.org/caldav/[KALENDER-ID]`

Die Kalender-ID ist Base64-kodiert und eindeutig für jeden Kalender.

### 2. Basic Auth Credential in n8n erstellen

**In n8n:**
1. **Settings** → **Credentials** → **"+ Add Credential"**
2. Suche: **"Basic Auth"**
3. **Name:** "mailbox.org CalDAV"
4. **User:** Deine mailbox.org Email (z.B. `dein-name@mailbox.org`)
5. **Password:** Dein mailbox.org Passwort
6. **Save**

**Sicherheitshinweis:** Falls du 2FA aktiviert hast, brauchst du ein App-Passwort:
- mailbox.org → Einstellungen → Sicherheit → App-Passwörter

### 3. Test-Workflow: Kalendereintrag erstellen

#### Workflow-Struktur:

```
1. Manual Trigger (Input-Daten)
   ↓
2. HTTP Request (CalDAV PUT)
   ↓
3. Erfolg: HTTP 201 Created
```

#### Node 1: Manual Trigger

**Output (Edit Using Expressions):**

```json
{
  "event_id": "test-123",
  "title": "Team Meeting",
  "description": "Weekly Standup"
}
```

**Für dynamische Termine später:**
- `start_date`: ISO-Format `2026-02-16`
- `start_time`: Format `14:00`
- `duration_minutes`: z.B. `60`

#### Node 2: HTTP Request

**Method:** `PUT`

**URL:**
```
https://dav.mailbox.org/caldav/Y2FsOi8vMC8zMQ/{{ $json.event_id }}.ics
```

**WICHTIG:** Ersetze `Y2FsOi8vMC8zMQ` mit deiner eigenen Kalender-ID!

**Authentication:**
- Typ: **"Predefined Credential Type"**
- Credential Type: **"Basic Auth"**
- Credential: **"mailbox.org CalDAV"** (wie in Schritt 2 erstellt)

**Send Headers:** ✅ Aktivieren
- **Name:** `Content-Type`
- **Value:** `text/calendar; charset=utf-8`

**Send Body:** ✅ Aktivieren
- **Body Content Type:** `Raw`
- **Specify Body:** `Using Fields Below`
- **Content Type:** `Text`

**Body:**

```
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Niles AI//DE
BEGIN:VEVENT
UID:{{ $json.event_id }}@niles
DTSTAMP:{{ $now.toFormat('yyyyMMdd\'T\'HHmmss\'Z\'') }}
DTSTART:{{ $now.plus({days: 1}).set({hour: 14, minute: 0}).toFormat('yyyyMMdd\'T\'HHmmss\'Z\'') }}
DTEND:{{ $now.plus({days: 1}).set({hour: 15, minute: 0}).toFormat('yyyyMMdd\'T\'HHmmss\'Z\'') }}
SUMMARY:{{ $json.title }}
DESCRIPTION:{{ $json.description }}
END:VEVENT
END:VCALENDAR
```

**WICHTIG:** Jede Zeile muss eine **neue Zeile** sein (Enter drücken)!

#### Workflow ausführen

1. **"Execute Workflow"** klicken
2. **Erwartetes Ergebnis:** HTTP 201 Created
3. **Kalender prüfen:** Event sollte in mailbox.org Web-Interface oder Thunderbird sichtbar sein

### 4. iCalendar Format verstehen

```ics
BEGIN:VCALENDAR              → Kalender-Container Start
VERSION:2.0                  → iCalendar Standard Version
PRODID:-//Niles AI//DE       → Producer Identifier (beliebig)
BEGIN:VEVENT                 → Event Start
UID:test-123@niles           → Unique ID (WICHTIG: Muss eindeutig sein!)
DTSTAMP:20260213T170000Z     → Timestamp wann Event erstellt wurde
DTSTART:20260216T140000Z     → Start-Zeitpunkt (UTC!)
DTEND:20260216T150000Z       → End-Zeitpunkt (UTC!)
SUMMARY:Team Meeting         → Event-Titel
DESCRIPTION:Weekly Standup   → Event-Beschreibung
END:VEVENT                   → Event Ende
END:VCALENDAR                → Kalender-Container Ende
```

**DateTime-Format:** `YYYYMMDDTHHmmssZ`
- Beispiel: `20260216T140000Z` = 16. Februar 2026, 14:00 Uhr UTC
- Das `Z` am Ende bedeutet UTC (wichtig!)

### 5. Dynamische Termine mit n8n Expressions

**Beispiel: Termin in 3 Tagen, 10:00 Uhr, 2 Stunden lang**

```
DTSTART:{{ $now.plus({days: 3}).set({hour: 10, minute: 0}).toFormat('yyyyMMdd\'T\'HHmmss\'Z\'') }}
DTEND:{{ $now.plus({days: 3}).set({hour: 12, minute: 0}).toFormat('yyyyMMdd\'T\'HHmmss\'Z\'') }}
```

**Verfügbare n8n DateTime-Funktionen:**
- `$now` - Aktueller Zeitpunkt
- `.plus({days: 1})` - Addieren (days, hours, minutes)
- `.minus({hours: 2})` - Subtrahieren
- `.set({hour: 14, minute: 30})` - Bestimmte Zeit setzen
- `.toFormat('yyyyMMdd\'T\'HHmmss\'Z\'')` - iCalendar-Format

### 6. Integration mit AI Agent (später)

**Custom Tool für n8n AI Agent:**

```json
{
  "name": "create_mailbox_calendar_event",
  "description": "Erstellt einen Kalendereintrag im lokalen mailbox.org Kalender",
  "parameters": {
    "type": "object",
    "properties": {
      "title": {
        "type": "string",
        "description": "Titel des Termins"
      },
      "date": {
        "type": "string",
        "description": "Datum im Format YYYY-MM-DD"
      },
      "time": {
        "type": "string",
        "description": "Uhrzeit im Format HH:MM"
      },
      "duration_minutes": {
        "type": "integer",
        "default": 60,
        "description": "Dauer in Minuten"
      },
      "description": {
        "type": "string",
        "description": "Optionale Beschreibung"
      }
    },
    "required": ["title", "date", "time"]
  }
}
```

## Wichtige Dateien

- `~/.n8n/workflows/mailbox-calendar-create.json` - Workflow
- `~/.n8n/database.sqlite` - Credentials (verschlüsselt)

## Verifikation

- [ ] CalDAV-URL von mailbox.org kopiert
- [ ] Basic Auth Credential in n8n erstellt
- [ ] Test-Workflow funktioniert (HTTP 201)
- [ ] Event in mailbox.org Kalender sichtbar
- [ ] Event in Thunderbird/iOS Kalender synchronisiert

## Troubleshooting

### Fehler: 403 Forbidden "No folder permission"

**Ursache:** Falsche CalDAV-URL oder fehlende Credentials

**Lösung:**
1. CalDAV-URL erneut aus mailbox.org Web-Interface kopieren
2. Basic Auth Credential prüfen (User = vollständige Email!)
3. Sicherstellen dass URL mit `/caldav/` beginnt

### Fehler: 400 Bad Request "Invalid iCalendar content" (ICAL-0007)

**Ursache:** Ungültiges iCalendar-Format im Body

**Häufige Probleme:**
1. **n8n Expressions nicht aufgelöst:**
   - Teste erst mit **fixem Content** (ohne `{{ }}`)
   - Wenn das funktioniert, füge Expressions hinzu

2. **Fehlende Zeilenumbrüche:**
   - Jede Zeile muss eine **neue Zeile** sein im Body-Feld
   - Nicht als einzelne Zeile mit `\n` einfügen

3. **Falsches DateTime-Format:**
   - Muss `YYYYMMDDTHHmmssZ` sein (mit `Z` am Ende!)
   - Beispiel: `20260216T140000Z`

**Debug mit curl:**

```bash
# Test-Event in Datei erstellen
cat > /tmp/test-event.ics << EOF
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//DE
BEGIN:VEVENT
UID:test-curl@niles
DTSTAMP:20260213T170000Z
DTSTART:20260216T100000Z
DTEND:20260216T110000Z
SUMMARY:Curl Test
END:VEVENT
END:VCALENDAR
EOF

# Via curl testen
curl -v -X PUT \
  -u "deine-email@mailbox.org:dein-passwort" \
  -H "Content-Type: text/calendar; charset=utf-8" \
  --data-binary @/tmp/test-event.ics \
  https://dav.mailbox.org/caldav/Y2FsOi8vMC8zMQ/test-curl.ics
```

**Erwartete Antwort:** `HTTP/2 201` (Created)

Falls curl funktioniert, aber n8n nicht → Body-Formatierung in n8n prüfen!

### Fehler: 405 Method Not Allowed

**Ursache:** Falsche HTTP-Methode

**Lösung:** Method muss **PUT** sein (nicht POST!)

### Event wird nicht aktualisiert (immer neue Events erstellt)

**Ursache:** Jeder PUT mit anderer UID erstellt ein neues Event

**Lösung:**
- Verwende **gleiche UID** für Updates: `UID:meeting-recurring@niles`
- Ändere nur Filename in URL: `/meeting-recurring-2026-02-16.ics`

**Für wiederkehrende Termine:**
- Gleiche UID + anderer Filename = neues Event
- Gleiche UID + gleicher Filename = Update

### Zeitzone-Probleme

**Problem:** Termine erscheinen 1-2 Stunden verschoben

**Ursache:** UTC (`Z`) vs. lokale Zeitzone

**Lösung 1: UTC verwenden (empfohlen)**
```
DTSTART:20260216T130000Z  ← 13:00 UTC = 14:00 CET
```

**Lösung 2: Zeitzone explizit angeben**
```
DTSTART;TZID=Europe/Berlin:20260216T140000
```

(Dann aber auch `VTIMEZONE` Block nötig - komplexer!)

## Vergleich: mailbox.org vs. Google Calendar

| Feature | mailbox.org CalDAV | Google Calendar |
|---------|-------------------|-----------------|
| **Privacy** | ✅ DSGVO, EU-Server | ⚠️ US-Cloud |
| **Setup** | ✅ Basic Auth (einfach) | ⚠️ OAuth2 (komplex) |
| **Offline** | ✅ Komplett offline | ❌ Cloud-abhängig |
| **n8n Integration** | ✅ HTTP Request Node | ✅ Native Google Node |
| **Funktionen** | ⚠️ Basis (Events, Todos) | ✅ Erweitert (Reminders, etc.) |
| **Kosten** | ✅ In mailbox.org enthalten | ✅ Free (mit Google Account) |

**Empfehlung:**
- **mailbox.org** für lokale, private Termine
- **Google Calendar** für geteilte Termine mit Kollegen/Freunden

## Nächste Schritte

→ [Phase 4: WhatsApp Integration](04-whatsapp.md)

Jetzt haben wir **zwei Kalender** im AI-Agenten:
- **Google Calendar** (für geteilte Termine)
- **mailbox.org CalDAV** (für private, lokale Termine)

Der AI-Agent kann später entscheiden, welchen Kalender er nutzt basierend auf dem Kontext!
