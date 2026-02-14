# Phase 5: AI Agent mit Tools in n8n

## Übersicht

Aufbau des vollständigen AI-Agenten mit allen Tools (Calendar, Email, Notizen) in n8n.

**Status:** Noch nicht implementiert

## Geplante Architektur

```
AI Agent (n8n)
├── LLM: LM Studio (Qwen2.5-Coder:7b)
├── Memory: Simple Memory
└── Tools:
    ├── create_calendar_event (Google Calendar)
    ├── search_emails (Gmail IMAP)
    ├── draft_email (Gmail SMTP)
    └── search_notes (Lokale Markdown-Dateien)
```

## Geplante Schritte

### 1. AI Agent Node konfigurieren

**In n8n:**
1. Neuer Workflow: "Niles AI Agent"
2. Node: "When chat message received"
3. Node: "AI Agent"
   - Chat Model: OpenAI → LM Studio Credential
   - Memory: Simple Memory
   - **"Use Response API": Deaktiviert**

### 2. Custom Tools hinzufügen

**Tool 1: create_calendar_event**
```json
{
  "name": "create_calendar_event",
  "description": "Erstellt einen Kalendereintrag in Google Calendar",
  "parameters": {
    "type": "object",
    "properties": {
      "title": {"type": "string"},
      "date": {"type": "string", "description": "Format: YYYY-MM-DD"},
      "time": {"type": "string", "description": "Format: HH:MM"},
      "duration_minutes": {"type": "integer", "default": 60}
    },
    "required": ["title", "date", "time"]
  }
}
```

**Tool 2: search_emails**
```json
{
  "name": "search_emails",
  "description": "Durchsucht Gmail nach Stichwort",
  "parameters": {
    "type": "object",
    "properties": {
      "query": {"type": "string"},
      "limit": {"type": "integer", "default": 10}
    },
    "required": ["query"]
  }
}
```

**Tool 3: search_notes**
```json
{
  "name": "search_notes",
  "description": "Durchsucht lokale Markdown-Notizen (Obsidian)",
  "parameters": {
    "type": "object",
    "properties": {
      "query": {"type": "string"}
    },
    "required": ["query"]
  }
}
```

### 3. System-Prompt optimieren

```
Du bist "Niles", ein persönlicher AI-Assistent der komplett lokal auf einem Mac Mini M4 läuft.

WICHTIG: Du läufst zu 100% offline und lokal. Alle Daten bleiben auf dem Mac.

Verfügbare Tools:
- create_calendar_event(title, date, time, duration_minutes)
- search_emails(query, limit)
- draft_email(to, subject, body)
- search_notes(query)

Regeln:
1. Antworte auf Deutsch
2. Frage nach wenn Informationen fehlen
3. Bestätige vor kritischen Aktionen
4. Sei präzise und effizient (KISS)
5. Weise auf Privacy-Vorteile hin ("Deine Daten bleiben lokal")

Persönlichkeit: Professionell, freundlich, proaktiv, datenschutz-bewusst
```

## Test-Szenarien

1. **Termin erstellen:** "Erstelle einen Termin morgen 14 Uhr, Zahnarzt"
2. **Emails suchen:** "Suche Emails von Max aus letzter Woche"
3. **Email-Entwurf:** "Schreibe eine Email an max@example.com zum Thema Meeting"
4. **Notizen durchsuchen:** "Was steht in meinen Notizen über das Projekt X?"

## Nächste Schritte

→ [Phase 6: Produktivbetrieb & Autostart](06-production.md)
