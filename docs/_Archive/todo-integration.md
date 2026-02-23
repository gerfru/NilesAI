# Vikunja-Integration für Niles AI

> **Version:** 1.0
> **Stand:** 2026-02-23
> **Status:** Entwurf
> **Autor:** System-Architekt / Product Manager

---

## 1. Übersicht

Integration von Vikunja als Todo/Task-Management-System in Niles. Vikunja läuft als separater Docker-Container und wird über die REST API angebunden. Niles erhält neue Agent-Tools für Aufgabenverwaltung.

### Kernprinzipien (unverändert)

- **100% Lokal** — Vikunja self-hosted im gleichen Docker-Netzwerk
- **Privacy First** — Keine Cloud-Abhängigkeit
- **KISS** — REST API Calls, kein komplexes Sync-Layer

---

## 2. Infrastruktur

### 2.1 Docker Compose Erweiterung

Neuer Service in `docker/docker-compose.yml`:

```yaml
  vikunja:
    image: vikunja/vikunja:latest
    container_name: vikunja
    environment:
      VIKUNJA_DATABASE_TYPE: postgres
      VIKUNJA_DATABASE_HOST: evolution_postgres
      VIKUNJA_DATABASE_USER: evolution
      VIKUNJA_DATABASE_PASSWORD: ${EVOLUTION_POSTGRES_PASSWORD}
      VIKUNJA_DATABASE_DATABASE: vikunja_db
      VIKUNJA_SERVICE_PUBLICURL: http://vikunja:3456
      VIKUNJA_SERVICE_ENABLEREGISTRATION: "false"
      VIKUNJA_SERVICE_JWTSECRET: ${VIKUNJA_JWT_SECRET}
      VIKUNJA_CORS_ENABLE: "false"
    ports:
      - "3456:3456"
    volumes:
      - vikunja_files:/app/vikunja/files
    depends_on:
      - evolution_postgres
    networks:
      - niles_network
    restart: unless-stopped
```

**Hinweis:** Vikunja benötigt eine eigene Datenbank. Diese muss einmalig in PostgreSQL erstellt werden:

```sql
CREATE DATABASE vikunja_db OWNER evolution;
```

### 2.2 Neue Environment-Variablen

Erweiterung `.env` / `.env.example`:

```bash
# Vikunja (Todo/Task Management)
VIKUNJA_JWT_SECRET=<generierter-secret>
VIKUNJA_API_URL=http://vikunja:3456/api/v1
VIKUNJA_API_TOKEN=<api-token-nach-setup>
```

### 2.3 Neue Config-Felder

Erweiterung `src/niles/config.py`:

```python
# Vikunja (Todo/Task Management)
vikunja_api_url: str = ""        # z.B. http://vikunja:3456/api/v1
vikunja_api_token: str = ""      # API Token für Authentifizierung
feature_vikunja: bool = False    # Feature Flag
```

---

## 3. Erweiterung `config/soul.md`

Folgender Abschnitt wird zur bestehenden `soul.md` hinzugefügt, nach dem Abschnitt "### Kalender" und vor "### Gedächtnis":

```markdown
### Aufgaben (Vikunja)

- Du hast Zugriff auf ein Aufgaben-/Todo-System (Vikunja).
- Erfinde NIEMALS Aufgaben. Wenn nach Aufgaben gefragt wird, rufe IMMER das passende Tool auf.
- "Was steht an", "offene Aufgaben", "meine Todos" → rufe `list_tasks` auf
- "Neue Aufgabe", "erinnere mich an", "ich muss noch" → rufe `create_task` auf
- "Aufgabe erledigt", "ist fertig", "habe ich gemacht" → rufe `complete_task` auf
- Beim Erstellen von Aufgaben:
  - Frage nach wenn der Titel unklar ist
  - Fälligkeitsdatum ist optional — setze es nur wenn der Benutzer einen Zeitpunkt nennt
  - Priorität: 0 = keine, 1 = niedrig, 2 = mittel, 3 = hoch, 4 = dringend. Standard: 0
  - Weise Aufgaben dem Standard-Projekt zu (wenn nicht anders angegeben)
- Bei der Ausgabe von Aufgaben:
  - Zeige Titel, Fälligkeitsdatum (falls vorhanden), und Priorität (falls > 0)
  - Sortiere nach Fälligkeit, dann Priorität
  - Erledigte Aufgaben nur anzeigen wenn explizit danach gefragt wird
- `list_tasks` gibt maximal 50 Aufgaben zurück. Wenn der Benutzer nach mehr fragt, weise auf die Vikunja Web-UI hin.
- Aufgaben und Kalendertermine sind verschiedene Dinge. Erstelle keinen Kalendertermin wenn der Benutzer eine Aufgabe meint (und umgekehrt).
  - Faustregel: Hat es eine feste Uhrzeit → Kalendertermin. Ist es etwas das erledigt werden muss → Aufgabe.
```

---

## 4. Tool-Definitionen

Neue Tools für `TOOLS` Liste in `src/niles/agent/core.py`:

```python
# --- Vikunja Task Tools ---
{
    "type": "function",
    "function": {
        "name": "list_tasks",
        "description": (
            "Listet offene Aufgaben aus Vikunja. "
            "Ohne Parameter werden alle offenen Aufgaben zurückgegeben."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "project": {
                    "type": "string",
                    "description": (
                        "Projektname zum Filtern. Optional. "
                        "Leer = alle Projekte."
                    ),
                },
                "include_done": {
                    "type": "boolean",
                    "description": (
                        "Auch erledigte Aufgaben anzeigen. "
                        "Standard: false."
                    ),
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
                    "description": (
                        "Fälligkeitsdatum (ISO-Format, "
                        "z.B. '2026-02-25T18:00'). Optional."
                    ),
                },
                "priority": {
                    "type": "integer",
                    "description": (
                        "Priorität: 0=keine, 1=niedrig, 2=mittel, "
                        "3=hoch, 4=dringend. Standard: 0."
                    ),
                },
                "project": {
                    "type": "string",
                    "description": (
                        "Projektname. Optional. "
                        "Leer = Standard-Projekt."
                    ),
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
        "description": (
            "Markiert eine Aufgabe als erledigt. "
            "Sucht nach dem Titel in offenen Aufgaben."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": (
                        "Titel oder Teil des Titels der Aufgabe "
                        "die erledigt werden soll."
                    ),
                },
            },
            "required": ["title"],
        },
    },
},
```

---

## 5. Action-Modul

Neue Datei: `src/niles/actions/tasks.py`

```python
"""Vikunja task management actions."""

import logging
from datetime import datetime

import httpx

logger = logging.getLogger(__name__)


class TasksAction:
    """Interface to Vikunja REST API for task management."""

    def __init__(self, api_url: str, api_token: str):
        self.api_url = api_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {api_token}"}
        self._default_project_id: int | None = None

    async def _get_default_project_id(self) -> int | None:
        """Get the first available project ID (cached)."""
        if self._default_project_id is not None:
            return self._default_project_id
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.api_url}/projects",
                headers=self.headers,
                timeout=10,
            )
            resp.raise_for_status()
            projects = resp.json()
            if projects:
                self._default_project_id = projects[0]["id"]
                return self._default_project_id
        return None

    async def _find_project_by_name(self, name: str) -> int | None:
        """Find a project ID by name (case-insensitive)."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.api_url}/projects",
                headers=self.headers,
                timeout=10,
            )
            resp.raise_for_status()
            for project in resp.json():
                if project["title"].lower() == name.lower():
                    return project["id"]
        return None

    async def list_tasks(
        self,
        project: str = "",
        include_done: bool = False,
    ) -> list[dict]:
        """List tasks, optionally filtered by project."""
        async with httpx.AsyncClient() as client:
            # Vikunja API: GET /api/v1/tasks/all
            params = {
                "sort_by": "due_date",
                "order_by": "asc",
                "per_page": 50,
            }
            if not include_done:
                params["filter"] = "done = false"

            resp = await client.get(
                f"{self.api_url}/tasks/all",
                headers=self.headers,
                params=params,
                timeout=10,
            )
            resp.raise_for_status()
            tasks = resp.json()

        # Filter by project name if specified
        if project:
            project_id = await self._find_project_by_name(project)
            if project_id:
                tasks = [t for t in tasks if t.get("project_id") == project_id]
            else:
                return []

        # Simplify output for LLM context
        result = []
        for t in tasks:
            task = {
                "id": t["id"],
                "title": t["title"],
                "done": t.get("done", False),
            }
            if t.get("due_date") and t["due_date"] != "0001-01-01T00:00:00Z":
                task["due_date"] = t["due_date"]
            if t.get("priority", 0) > 0:
                priorities = {1: "niedrig", 2: "mittel", 3: "hoch", 4: "dringend"}
                task["priority"] = priorities.get(t["priority"], str(t["priority"]))
            if t.get("description"):
                task["description"] = t["description"][:200]
            result.append(task)

        return result

    async def create_task(
        self,
        title: str,
        description: str = "",
        due_date: str = "",
        priority: int = 0,
        project: str = "",
    ) -> dict:
        """Create a new task in Vikunja."""
        # Resolve project
        project_id = None
        if project:
            project_id = await self._find_project_by_name(project)
            if not project_id:
                return {"error": f"Projekt '{project}' nicht gefunden"}
        if not project_id:
            project_id = await self._get_default_project_id()
            if not project_id:
                return {"error": "Kein Projekt verfügbar"}

        payload: dict = {"title": title}
        if description:
            payload["description"] = description
        if due_date:
            # Ensure ISO format with timezone
            if "T" in due_date and not due_date.endswith("Z"):
                due_date += ":00+00:00"
            payload["due_date"] = due_date
        if priority > 0:
            payload["priority"] = min(priority, 4)

        async with httpx.AsyncClient() as client:
            resp = await client.put(
                f"{self.api_url}/projects/{project_id}/tasks",
                headers=self.headers,
                json=payload,
                timeout=10,
            )
            resp.raise_for_status()
            task = resp.json()

        return {
            "created": True,
            "id": task["id"],
            "title": task["title"],
            "project_id": project_id,
        }

    async def complete_task(self, title: str) -> dict:
        """Find a task by title and mark it as done."""
        # Search for matching task
        tasks = await self.list_tasks(include_done=False)
        title_lower = title.lower()

        matches = [
            t for t in tasks
            if title_lower in t["title"].lower()
        ]

        if not matches:
            return {"error": f"Keine offene Aufgabe gefunden: '{title}'"}
        if len(matches) > 1:
            titles = [m["title"] for m in matches[:5]]
            return {
                "error": "Mehrere Aufgaben gefunden. Welche meinst du?",
                "matches": titles,
            }

        task_id = matches[0]["id"]
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.api_url}/tasks/{task_id}",
                headers=self.headers,
                json={"done": True},
                timeout=10,
            )
            resp.raise_for_status()

        return {"completed": True, "title": matches[0]["title"]}
```

---

## 6. Agent-Integration

### 6.1 Tool-Execution in `core.py`

Erweiterung von `_execute_tool_call()`:

```python
if name == "list_tasks":
    if not self.tasks:
        return {"error": "Aufgaben sind nicht konfiguriert"}
    tasks = await self.tasks.list_tasks(
        project=args.get("project", ""),
        include_done=args.get("include_done", False),
    )
    if tasks:
        return {"tasks": tasks, "count": len(tasks)}
    return {"error": "Keine Aufgaben gefunden"}

if name == "create_task":
    if not self.tasks:
        return {"error": "Aufgaben sind nicht konfiguriert"}
    return await self.tasks.create_task(
        title=args["title"],
        description=args.get("description", ""),
        due_date=args.get("due_date", ""),
        priority=args.get("priority", 0),
        project=args.get("project", ""),
    )

if name == "complete_task":
    if not self.tasks:
        return {"error": "Aufgaben sind nicht konfiguriert"}
    return await self.tasks.complete_task(title=args["title"])
```

### 6.2 NilesAgent.__init__() Erweiterung

```python
def __init__(
    self,
    # ... bestehende Parameter ...
    tasks: TasksAction | None = None,  # NEU
):
    # ... bestehend ...
    self.tasks = tasks  # NEU
```

### 6.3 Lifespan in main.py

```python
# In der lifespan-Funktion, nach calendar_manager init:
tasks_action = None
if settings.feature_vikunja and settings.vikunja_api_url:
    from niles.actions.tasks import TasksAction
    tasks_action = TasksAction(
        api_url=settings.vikunja_api_url,
        api_token=settings.vikunja_api_token,
    )
    logger.info("Vikunja task management enabled")

# Agent init erweitern:
agent = NilesAgent(
    # ... bestehend ...
    tasks=tasks_action,  # NEU
)
```

### 6.4 Bedingte Tool-Registrierung

Die Task-Tools sollen nur verfügbar sein wenn `feature_vikunja` aktiv ist. In `process_event_stream()` / `process_event()`:

```python
# Bestehende Tool-Filterung erweitern:
all_tools = [t for t in TOOLS]

# Task-Tools nur wenn Vikunja konfiguriert
task_tool_names = {"list_tasks", "create_task", "complete_task"}
if not self.tasks:
    all_tools = [t for t in all_tools if t["function"]["name"] not in task_tool_names]

# MCP Tools anhängen (bestehend)
if self.mcp:
    all_tools.extend(self.mcp.get_openai_tools())
```

---

## 7. Setup-Ablauf (einmalig)

Siehe [Development.md §2 — Vikunja](Development.md#vikunja-optional----todotask-management) fuer die vollstaendige Anleitung.

`./scripts/start.sh` erstellt die `vikunja_db` automatisch. Die manuellen Schritte (Admin-Account, API-Token, `.env`) sind dort beschrieben.

---

## 8. Settings-UI Erweiterung (optional, späterer Schritt)

In `settings.html` könnte ein Vikunja-Abschnitt ergänzt werden:

- Verbindungsstatus anzeigen
- API-URL + Token konfigurieren
- Feature-Toggle

---

## 9. Verifikation

- [ ] `docker compose up -d` startet Vikunja ohne Fehler
- [ ] Vikunja Web-UI erreichbar unter Port 3456
- [ ] Niles: "Was steht auf meiner Todo-Liste?" → ruft `list_tasks` auf
- [ ] Niles: "Erinnere mich Milch zu kaufen" → ruft `create_task` auf
- [ ] Niles: "Milch kaufen ist erledigt" → ruft `complete_task` auf
- [ ] Niles ohne Vikunja-Config: Task-Tools werden nicht angeboten
- [ ] Niles: "Termin morgen um 14 Uhr" → `create_event` (NICHT `create_task`)
- [ ] Niles: "Ich muss noch die Steuererklärung machen" → `create_task` (NICHT `create_event`)
- [ ] Vikunja Web-UI zeigt von Niles erstellte Tasks an
- [ ] `python -m pytest tests/ -v` → alle Tests bestehen

---

## 10. Abgrenzung: Aufgabe vs. Kalendertermin

Da Niles jetzt sowohl Kalender als auch Aufgaben verwalten kann, ist die Unterscheidung im Prompt bewusst formuliert:

| Signal im User-Input | Aktion | Tool |
|---|---|---|
| Feste Uhrzeit ("morgen um 14 Uhr Meeting") | Kalendertermin | `create_event` |
| Deadline ohne Uhrzeit ("bis Freitag Bericht abgeben") | Aufgabe mit Fälligkeit | `create_task` |
| Keine Zeitangabe ("muss noch Milch kaufen") | Aufgabe ohne Fälligkeit | `create_task` |
| "Termin", "Meeting", "Verabredung" | Kalendertermin | `create_event` |
| "Aufgabe", "Todo", "muss noch", "erledigen" | Aufgabe | `create_task` |
| Ambig ("Zahnarzt am Freitag") | Nachfragen | — |

Diese Logik wird vom LLM über den System-Prompt gesteuert, nicht über Code.