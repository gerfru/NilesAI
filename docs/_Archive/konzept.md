# Lokaler AI-Agent mit Ollama auf dem Mac Mini M4

## Projektziel

Einen lokal betriebenen AI-Agenten aufsetzen, der über natürliche Sprache Alltagsaufgaben erledigt: Kalendereinträge erstellen, Reservierungen vorbereiten, E-Mails entwerfen und Workflows automatisieren – alles ohne Cloud-Abhängigkeit.

---

## Phase 0: Bestandsaufnahme – Gibt es das schon? (Vor dem Start)

Bevor du alles selbst baust, lohnt sich ein Blick auf bestehende Open-Source-Projekte und Community-Lösungen, die lokale LLMs bereits als Agenten mit Tool-Zugriff einsetzen. Das Ökosystem entwickelt sich schnell – möglicherweise gibt es bereits fertige oder halbfertige Lösungen, die dir Wochen an Eigenentwicklung ersparen.

### Wonach suchen?

| Kategorie | Suchbegriffe / Projekte zum Prüfen |
|---|---|
| **All-in-One Agenten** | Local AI Assistant, Private GPT Agent, Self-hosted AI Agent |
| **Tool-Calling Frameworks** | LangChain Agents, CrewAI, AutoGen, Semantic Kernel |
| **Ollama-spezifisch** | Open WebUI Functions/Tools, Ollama + MCP, Ollama Agent Frameworks |
| **Personal Assistant Projekte** | Leon AI, Mycroft/OVOS, Home Assistant + LLM |
| **MCP-Ökosystem** | Model Context Protocol Servers (Kalender, E-Mail, Notizen) |

### Wo suchen?

- **GitHub:** Suche nach `ollama agent`, `local llm assistant`, `self-hosted ai agent`
- **Reddit:** r/LocalLLaMA, r/selfhosted – aktive Communities mit Erfahrungsberichten
- **Awesome-Listen:** `awesome-ollama`, `awesome-local-ai`, `awesome-mcp-servers`
- **Open WebUI Community:** Geteilte Functions und Pipelines im Open WebUI Marketplace

### Bewertungskriterien

Wenn du ein bestehendes Projekt findest, prüfe:

- [ ] Wird es aktiv gepflegt? (Letzter Commit < 3 Monate)
- [ ] Unterstützt es Ollama als Backend?
- [ ] Gibt es Kalender-/E-Mail-Integration oder Plugins dafür?
- [ ] Wie groß ist die Community? (Stars, Issues, Discussions)
- [ ] Läuft es auf macOS / ARM (Apple Silicon)?
- [ ] Wie ist die Dokumentation?

> **Ziel:** Entweder ein bestehendes Projekt als Basis nehmen und anpassen, oder bewusst entscheiden, es selbst zu bauen – aber informiert statt redundant.

---

## Phase 1: Grundinstallation (Tag 1)

### 1.1 Ollama installieren

```bash
brew install ollama
ollama serve
```

### 1.2 Modell auswählen und laden

| Modell | Größe | Eignung für Function Calling | RAM-Bedarf |
|---|---|---|---|
| Llama 3.1 8B | 4.7 GB | Gut für einfache Tasks | ~8 GB |
| Mistral Nemo 12B | 7.1 GB | Besser für komplexe Anweisungen | ~12 GB |
| Qwen 2.5 14B | 8.9 GB | Stark bei strukturiertem Output | ~14 GB |
| Llama 3.1 70B (Q4) | ~40 GB | Beste Qualität, braucht 64 GB RAM | ~48 GB |

> **Empfehlung für Mac Mini M4 mit 16 GB RAM:** Starte mit `llama3.1:8b` oder `qwen2.5:14b` (läuft knapp, aber geht).
> Bei 24 GB+ RAM ist `mistral-nemo` oder `qwen2.5:14b` komfortabler.

```bash
ollama pull llama3.1:8b
# Test:
ollama run llama3.1:8b "Erstelle einen JSON-Kalendereintrag für morgen 14 Uhr, Zahnarzt"
```

### 1.3 Validierung

- [ ] Ollama läuft als Daemon (`ollama serve`)
- [ ] API erreichbar unter `http://localhost:11434`
- [ ] Modell antwortet auf Prompts
- [ ] Structured Output (JSON) funktioniert zuverlässig

---

## Phase 2: Frontend & Interface (Tag 2–3)

### 2.1 Open WebUI installieren

```bash
docker run -d -p 3000:8080 \
  --add-host=host.docker.internal:host-gateway \
  -v open-webui:/app/backend/data \
  --name open-webui \
  --restart always \
  ghcr.io/open-webui/open-webui:main
```

> Erreichbar unter `http://localhost:3000`

### 2.2 Ollama als Backend verbinden

In Open WebUI unter **Settings → Connections**:
- Ollama URL: `http://host.docker.internal:11434`

### 2.3 Validierung

- [ ] Open WebUI zeigt verfügbare Modelle
- [ ] Chat funktioniert über Browser
- [ ] Antwortzeiten sind akzeptabel (< 5 Sekunden für kurze Antworten)

---

## Phase 3: Tool-Integration – Kalender (Tag 4–7)

### 3.1 Ansatz wählen

| Option | Vorteil | Nachteil |
|---|---|---|
| **Open WebUI Functions** | Direkt im UI integriert | Begrenzte Komplexität |
| **Python + LangChain** | Flexibel, erweiterbar | Mehr Entwicklungsaufwand |
| **n8n Workflow** | Visueller Builder, viele Integrationen | Zusätzliche Infrastruktur |

> **Empfehlung:** Starte mit Open WebUI Functions für den Kalender-Use-Case. Wechsle zu LangChain wenn du mehr Kontrolle brauchst.

### 3.2 CalDAV für Apple Calendar

Apple Calendar nutzt CalDAV. Lokaler Zugriff über:

```python
# Beispiel: caldav-Library
pip install caldav

import caldav

url = "http://localhost:8008"  # oder iCloud CalDAV URL
client = caldav.DAVClient(url=url, username="...", password="...")
calendar = client.principal().calendars()[0]

# Event erstellen
calendar.save_event("""
BEGIN:VCALENDAR
BEGIN:VEVENT
DTSTART:20260214T140000
DTEND:20260214T150000
SUMMARY:Zahnarzt
END:VEVENT
END:VCALENDAR
""")
```

### 3.3 Alternative: Google Calendar API

```python
pip install google-api-python-client google-auth-oauthlib

# OAuth2 Setup nötig → credentials.json von Google Cloud Console
# Scopes: https://www.googleapis.com/auth/calendar
```

### 3.4 Open WebUI Function registrieren

In Open WebUI unter **Workspace → Functions** eine neue Function anlegen:

```python
class Tools:
    def create_calendar_event(self, title: str, date: str, time: str, duration_minutes: int = 60) -> str:
        """Erstellt einen Kalendereintrag"""
        # CalDAV oder Google Calendar API Call hier
        return f"Event '{title}' am {date} um {time} erstellt."
```

### 3.5 Validierung

- [ ] CalDAV-Verbindung steht
- [ ] Events werden korrekt im Kalender angezeigt
- [ ] LLM ruft die Funktion zuverlässig auf natürliche Sprache hin auf
- [ ] Fehlerbehandlung bei ungültigen Daten

---

## Phase 4: Weitere Tools (Tag 8–14)

### 4.1 Mögliche Erweiterungen

| Tool | Zweck | API/Methode |
|---|---|---|
| **E-Mail-Entwurf** | E-Mails vorbereiten | IMAP/SMTP oder Gmail API |
| **Notizen** | Notizen erstellen/durchsuchen | Obsidian Vault (lokale Markdown-Dateien) |
| **Erinnerungen** | Zeitbasierte Alerts | Apple Shortcuts + CalDAV |
| **Web-Recherche** | Infos suchen | SearXNG (lokal) oder Tavily API |
| **Reservierungen** | Restaurant/Hotel vorbereiten | [Nicht automatisierbar] – LLM bereitet Text vor, du bestätigst manuell |

### 4.2 Zu Reservierungen

> **Wichtig:** Echte Reservierungen bei Restaurants, Hotels etc. lassen sich nicht vollautomatisch durchführen – die meisten Buchungsplattformen haben keine offene API für Endnutzer. Der Agent kann aber:
> - Verfügbarkeiten recherchieren (via Web-Suche)
> - Reservierungsanfragen als E-Mail/Text vorbereiten
> - Bestätigungen tracken

---

## Phase 5: Robustheit & Alltag (Tag 15–21)

### 5.1 System-Prompt optimieren

Erstelle einen dedizierten System-Prompt für deinen Agenten:

```
Du bist ein persönlicher Assistent. Du hast Zugriff auf folgende Tools:
- create_calendar_event(title, date, time, duration_minutes)
- draft_email(to, subject, body)
- search_notes(query)

Regeln:
- Frage nach, wenn Informationen fehlen (z.B. Uhrzeit)
- Bestätige immer vor einer Aktion
- Antworte auf Deutsch
```

### 5.2 Ollama als Autostart

```bash
# LaunchAgent erstellen
cat > ~/Library/LaunchAgents/com.ollama.serve.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.ollama.serve</string>
    <key>ProgramArguments</key>
    <array>
        <string>/opt/homebrew/bin/ollama</string>
        <string>serve</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
EOF

launchctl load ~/Library/LaunchAgents/com.ollama.serve.plist
```

### 5.3 Zugriff von unterwegs (via Tailscale)

Da du bereits Tailscale nutzt, kannst du deinen Agenten von überall erreichen:

```
http://[mac-mini-tailscale-ip]:3000
```

> Kein Port-Forwarding nötig, verschlüsselt durch WireGuard.

### 5.4 Validierung

- [ ] Ollama startet automatisch nach Reboot
- [ ] Open WebUI ist via Tailscale erreichbar
- [ ] Agent funktioniert zuverlässig im Alltag
- [ ] Fehlerhafte Tool-Calls werden abgefangen

---

## Phase 6: Evaluation & Iteration (fortlaufend)

### 6.1 Bekannte Limitierungen

| Bereich | Limitation |
|---|---|
| **Function Calling** | [Nicht verifiziert] Lokale Modelle (8B–14B) sind bei komplexem Tool-Calling weniger zuverlässig als Cloud-Modelle |
| **Geschwindigkeit** | Abhängig von Modellgröße und RAM – größere Modelle = langsamere Antworten |
| **Kontextlänge** | Die meisten lokalen Modelle: 8K–32K Token Kontext |
| **Deutsch** | [Nicht verifiziert] Manche Open-Source-Modelle performen auf Deutsch schwächer als auf Englisch |

### 6.2 Upgrade-Pfade

- **Mehr RAM** → Größere Modelle (70B) für bessere Qualität
- **Hybrid-Setup** → Lokales LLM für einfache Tasks, Cloud-API (Claude/OpenAI) für komplexe
- **MCP (Model Context Protocol)** → Standardisiertes Tool-Protokoll, wachsendes Ökosystem
- **Home Assistant** → Smart-Home-Integration als weiterer Agent-Kanal

---

## Zusammenfassung der Architektur

```
┌─────────────────────────────────────────────┐
│              Mac Mini M4                     │
│                                              │
│  ┌──────────┐    ┌─────────────────────┐    │
│  │  Ollama   │◄──│   Open WebUI         │    │
│  │  (LLM)   │    │   (Frontend + Tools) │    │
│  └──────────┘    └────────┬────────────┘    │
│                           │                  │
│              ┌────────────┼────────────┐     │
│              │            │            │     │
│         ┌────▼───┐  ┌────▼───┐  ┌────▼───┐ │
│         │CalDAV  │  │ E-Mail │  │ Notizen│  │
│         │Kalender│  │IMAP/   │  │Obsidian│  │
│         │        │  │SMTP    │  │Vault   │  │
│         └────────┘  └────────┘  └────────┘  │
│                                              │
│  ◄──── Tailscale VPN ────► Zugriff mobil    │
└─────────────────────────────────────────────┘
```

---

## Geschätzter Zeitaufwand

| Phase | Dauer | Schwierigkeit |
|---|---|---|
| Phase 1: Grundinstallation | 1 Tag | Einfach |
| Phase 2: Frontend | 2 Tage | Einfach |
| Phase 3: Kalender-Tool | 4 Tage | Mittel |
| Phase 4: Weitere Tools | 7 Tage | Mittel–Schwer |
| Phase 5: Robustheit | 7 Tage | Mittel |
| Phase 6: Iteration | Fortlaufend | – |

**Gesamt bis zum funktionierenden Kalender-Agenten: ca. 1 Woche**
**Gesamt bis zum erweiterten Agenten: ca. 3 Wochen**