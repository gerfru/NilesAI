# SPDX-License-Identifier: AGPL-3.0-only
"""Tool definitions for the Niles agent in OpenAI function-calling format."""

# Tool definitions in OpenAI function-calling format
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "find_contact",
            "description": "Sucht einen Kontakt nach Name und gibt alle Telefonnummern (phone = bevorzugte, phones = alle mit Typ) und Email zurück.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Name des Kontakts (oder Teil davon)",
                    }
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_whatsapp",
            "description": "Sendet eine WhatsApp-Nachricht an eine Telefonnummer oder einen Kontaktnamen.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {
                        "type": "string",
                        "description": "Telefonnummer (z.B. '436601234567') oder Kontaktname",
                    },
                    "text": {
                        "type": "string",
                        "description": "Nachrichtentext",
                    },
                },
                "required": ["to", "text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_whatsapp_messages",
            # Summarization instruction (2/3) — keep in sync with:
            # 1/3: config/soul.md "Nachrichten lesen"
            # 3/3: hinweis field in get_whatsapp_messages result below
            "description": (
                "Liest WhatsApp-Nachrichten aus einem Chat (max. 30 Tage). "
                "Suche nach Kontaktname oder Telefonnummer. "
                "Gibt ein Transcript zurueck. "
                "Nach dem Lesen: fasse die wichtigsten Punkte zusammen "
                "(Termine, Abmachungen, offene Fragen, wichtige Infos). "
                "Gib NICHT das rohe Transcript wieder."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "contact": {
                        "type": "string",
                        "description": ("Kontaktname oder Telefonnummer (erforderlich)."),
                    },
                },
                "required": ["contact"],
            },
        },
    },
    # --- Signal Tools ---
    {
        "type": "function",
        "function": {
            "name": "send_signal",
            "description": "Sendet eine Signal-Nachricht an eine Telefonnummer oder einen Kontaktnamen.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {
                        "type": "string",
                        "description": "Telefonnummer (z.B. '+4366012345678') oder Kontaktname",
                    },
                    "text": {
                        "type": "string",
                        "description": "Nachrichtentext",
                    },
                },
                "required": ["to", "text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_signal_messages",
            "description": (
                "Liest Signal-Nachrichten aus einem Chat (max. 30 Tage). "
                "Suche nach Kontaktname oder Telefonnummer. "
                "Gibt ein Transcript zurueck. "
                "Nach dem Lesen: fasse die wichtigsten Punkte zusammen "
                "(Termine, Abmachungen, offene Fragen, wichtige Infos). "
                "Gib NICHT das rohe Transcript wieder."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "contact": {
                        "type": "string",
                        "description": ("Kontaktname oder Telefonnummer (erforderlich)."),
                    },
                },
                "required": ["contact"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remember",
            "description": "Speichert einen Fakt oder eine Information dauerhaft im Gedächtnis. Nutze einen kurzen, beschreibenden Schlüssel.",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "Kurzer Schlüssel (z.B. 'zahnarzt_termin', 'lieblings_essen')",
                    },
                    "value": {
                        "type": "string",
                        "description": "Der zu merkende Inhalt",
                    },
                },
                "required": ["key", "value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recall",
            "description": "Ruft eine gespeicherte Information aus dem Gedächtnis ab.",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "Schlüssel der gespeicherten Information",
                    },
                },
                "required": ["key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_event",
            "description": "Liest bestehende Kalendertermine aus der Datenbank. Nutze dieses Tool wenn der Benutzer nach Terminen fragt, wissen will wann etwas stattfindet, oder seinen Kalender sehen will. Wenn nur date_from angegeben wird, werden automatisch nur Termine an diesem Tag zurueckgegeben.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Suchbegriff (Name, Ort, Beschreibung). Leer lassen fuer reine Datumssuche.",
                    },
                    "date_from": {
                        "type": "string",
                        "description": "Startdatum (ISO-Format, z.B. '2026-02-20'). Bei 'morgen' oder einem einzelnen Tag NUR date_from setzen, NICHT date_to.",
                    },
                    "date_to": {
                        "type": "string",
                        "description": "Enddatum (ISO-Format). Nur setzen bei expliziten Zeitraeumen wie 'diese Woche' oder 'naechste 7 Tage'. NICHT setzen bei Fragen nach einem einzelnen Tag.",
                    },
                    "calendar": {
                        "type": "string",
                        "description": "Kalenderquelle zum Filtern (z.B. 'Geburtstage', 'Arbeit'). NUR bei Geburtstags-Fragen oder wenn der Benutzer explizit einen bestimmten Kalender nennt. Bei allgemeinen Fragen wie 'was steht an' NICHT setzen — leer lassen damit alle Kalender durchsucht werden.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_event",
            "description": "Erstellt einen NEUEN Kalendertermin via CalDAV. Nur verwenden wenn der Benutzer explizit einen neuen Termin anlegen will.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "Titel des Termins",
                    },
                    "start": {
                        "type": "string",
                        "description": "Startzeit (ISO-Format, z.B. '2026-02-20T14:00')",
                    },
                    "end": {
                        "type": "string",
                        "description": "Endzeit (ISO-Format). Optional, Standard: 1 Stunde nach Start.",
                    },
                    "description": {
                        "type": "string",
                        "description": "Beschreibung des Termins. Optional.",
                    },
                    "location": {
                        "type": "string",
                        "description": "Ort des Termins. Optional.",
                    },
                },
                "required": ["summary", "start"],
            },
        },
    },
    # --- Vikunja Task Tools ---
    {
        "type": "function",
        "function": {
            "name": "list_tasks",
            "description": (
                "Listet offene Aufgaben aus Vikunja. Ohne Parameter werden alle offenen Aufgaben zurückgegeben."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "project": {
                        "type": "string",
                        "description": ("Projektname zum Filtern. Optional. Leer = alle Projekte."),
                    },
                    "include_done": {
                        "type": "boolean",
                        "description": ("Auch erledigte Aufgaben anzeigen. Standard: false."),
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_task",
            "description": (
                "Erstellt eine neue Aufgabe in Vikunja. "
                "Nur verwenden wenn der Benutzer explizit eine Aufgabe "
                "oder ein Todo anlegen will."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Titel der Aufgabe.",
                    },
                    "description": {
                        "type": "string",
                        "description": "Beschreibung der Aufgabe. Optional.",
                    },
                    "due_date": {
                        "type": "string",
                        "description": ("Fälligkeitsdatum (ISO-Format, z.B. '2026-02-25T18:00'). Optional."),
                    },
                    "priority": {
                        "type": "integer",
                        "description": ("Priorität: 0=keine, 1=niedrig, 2=mittel, 3=hoch, 4=dringend. Standard: 0."),
                    },
                    "project": {
                        "type": "string",
                        "description": ("Projektname. Optional. Leer = Standard-Projekt."),
                    },
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "complete_task",
            "description": ("Markiert eine Aufgabe als erledigt. Sucht nach dem Titel in offenen Aufgaben."),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": ("Titel oder Teil des Titels der Aufgabe die erledigt werden soll."),
                    },
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_notion",
            "description": (
                "Durchsucht die Notion-Wissensdatenbank nach relevanten Inhalten. "
                "Nutze dieses Tool wenn der Benutzer nach Informationen fragt, "
                "die in seinen Notion-Seiten stehen koennten (Dokumentation, "
                "Notizen, Projekte, Wikis)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Suchanfrage in natuerlicher Sprache",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximale Anzahl Ergebnisse (1-10, Standard: 5)",
                    },
                },
                "required": ["query"],
            },
        },
    },
]

MAX_TOOL_ROUNDS = 5
