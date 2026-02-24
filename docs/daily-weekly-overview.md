# Niles AI – Tägliche & Wöchentliche Übersicht (Briefing)

> **Version:** 1.2
> **Stand:** 2026-02-24
> **Status:** Umgesetzt
>
> **Hinweis:** `briefing_whatsapp_number` wurde entfernt. Die Empfaenger-Nummer wird automatisch ueber die verbundene WhatsApp-Instanz erkannt (`get_connection_state` + `get_owner_jid`). Details siehe implementierten Code in `src/niles/jobs/briefing.py`.
> **Autor:** System-Architekt / Product Manager

---

## 1. Übersicht

Niles sendet automatisch Zusammenfassungen an die eigene WhatsApp-Nummer:

- **Tägliches Briefing** — Mo–Fr um 07:30, heutige Termine + Tasks
- **Wochen-Übersicht** — Montag um 07:15, alle Termine der Woche nach Tagen

Am Montag kommen beide: erst 07:15 die Woche, dann 07:30 der Tag.
Am Wochenende kommt nichts.

Kein LLM nötig. Reine Datenbankabfragen + Template-Formatierung. KISS.

### Kernprinzipien (unverändert)

- **100% Lokal** — Nur bestehende Infrastruktur (PostgreSQL, APScheduler, Evolution API)
- **KISS** — Kein LLM-Call, kein neuer Service, kein neues Tool
- **Konfigurierbar** — Uhrzeit, Empfänger-Nummer, Feature-Flags via Settings

---

## 2. Config-Erweiterung

### 2.1 `src/niles/config.py`

```python
# Briefing / Digest
feature_briefing_daily: bool = False
feature_briefing_weekly: bool = False
briefing_daily_time: str = "07:30"             # HH:MM, Mo-Fr
briefing_weekly_time: str = "07:15"            # HH:MM, Montag
briefing_whatsapp_number: str = ""             # Eigene Nummer, z.B. "436601234567"
```

### 2.2 `.env.example`

```bash
# Briefing (Tägliche/Wöchentliche Übersicht via WhatsApp)
FEATURE_BRIEFING_DAILY=false
FEATURE_BRIEFING_WEEKLY=false
BRIEFING_DAILY_TIME=07:30
BRIEFING_WEEKLY_TIME=07:15
BRIEFING_WHATSAPP_NUMBER=436601234567
```

### 2.3 `settings_store.py` – EDITABLE_SETTINGS erweitern

```python
EDITABLE_SETTINGS = {
    # ... bestehend ...
    "feature_briefing_daily",
    "feature_briefing_weekly",
    "briefing_daily_time",
    "briefing_weekly_time",
    "briefing_whatsapp_number",
}
```

---

## 3. Briefing-Modul

Neue Datei: `src/niles/actions/briefing.py`

```python
"""Daily and weekly briefing generator."""

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import asyncpg

logger = logging.getLogger(__name__)

# Priority labels (matching Vikunja convention)
_PRIORITY = {1: "⬇️", 2: "➡️", 3: "⬆️", 4: "🔴"}


class BriefingGenerator:
    """Generates formatted briefing messages from calendar + tasks."""

    def __init__(
        self,
        pool: asyncpg.Pool,
        timezone: str = "Europe/Vienna",
        vikunja_api_url: str = "",
        vikunja_api_token: str = "",
    ):
        self.pool = pool
        self.tz = ZoneInfo(timezone)
        self.vikunja_api_url = vikunja_api_url.rstrip("/") if vikunja_api_url else ""
        self.vikunja_api_token = vikunja_api_token

    # -----------------------------------------------------------------
    # Datenabfragen
    # -----------------------------------------------------------------

    async def _get_events_for_range(
        self, date_from: datetime, date_to: datetime,
    ) -> list[dict]:
        """Fetch calendar events within a date range."""
        rows = await self.pool.fetch(
            """
            SELECT summary, dtstart, dtend, all_day, location,
                   cs.name AS calendar_name
            FROM events e
            LEFT JOIN calendar_sources cs ON e.source_id = cs.id
            WHERE dtstart >= $1 AND dtstart <= $2
            ORDER BY dtstart ASC
            """,
            date_from,
            date_to,
        )
        return [dict(r) for r in rows]

    async def _get_open_tasks(self) -> list[dict]:
        """Fetch open tasks from Vikunja API.

        Returns simplified task list, or empty list if Vikunja
        is not configured or not reachable.
        """
        if not self.vikunja_api_url or not self.vikunja_api_token:
            return []

        import httpx

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{self.vikunja_api_url}/tasks/all",
                    headers={"Authorization": f"Bearer {self.vikunja_api_token}"},
                    params={
                        "filter": "done = false",
                        "sort_by": "due_date",
                        "order_by": "asc",
                        "per_page": 20,
                    },
                    timeout=10,
                )
                resp.raise_for_status()
                tasks = resp.json()
        except Exception as e:
            logger.warning("Briefing: Vikunja nicht erreichbar: %s", e)
            return []

        result = []
        for t in tasks:
            task = {"title": t["title"], "id": t["id"]}
            due = t.get("due_date", "")
            if due and due != "0001-01-01T00:00:00Z":
                task["due_date"] = due
            prio = t.get("priority", 0)
            if prio > 0:
                task["priority"] = prio
            result.append(task)
        return result

    async def _get_overdue_tasks(self) -> list[dict]:
        """Filter open tasks that are past their due date."""
        tasks = await self._get_open_tasks()
        now = datetime.now(tz=self.tz)
        overdue = []
        for t in tasks:
            if "due_date" in t:
                try:
                    due = datetime.fromisoformat(
                        t["due_date"].replace("Z", "+00:00")
                    )
                    if due < now:
                        overdue.append(t)
                except (ValueError, TypeError):
                    pass
        return overdue

    # -----------------------------------------------------------------
    # Formatierung
    # -----------------------------------------------------------------

    def _format_event(self, event: dict) -> str:
        """Format a single calendar event as a WhatsApp-friendly line."""
        dt = event["dtstart"]
        if event.get("all_day"):
            time_str = "ganztägig"
        else:
            local_dt = dt.astimezone(self.tz) if dt.tzinfo else dt
            time_str = local_dt.strftime("%H:%M")

        line = f"• {time_str} — {event['summary']}"
        if event.get("location"):
            line += f" 📍 {event['location']}"
        return line

    def _format_task(self, task: dict) -> str:
        """Format a single task as a WhatsApp-friendly line."""
        prio_icon = _PRIORITY.get(task.get("priority", 0), "")
        prefix = f"{prio_icon} " if prio_icon else "• "
        line = f"{prefix}{task['title']}"
        if "due_date" in task:
            try:
                due = datetime.fromisoformat(
                    task["due_date"].replace("Z", "+00:00")
                )
                local_due = due.astimezone(self.tz)
                line += f" (fällig: {local_due.strftime('%d.%m.')})"
            except (ValueError, TypeError):
                pass
        return line

    def _weekday_de(self, dt: datetime) -> str:
        """Return German weekday name."""
        names = [
            "Montag", "Dienstag", "Mittwoch", "Donnerstag",
            "Freitag", "Samstag", "Sonntag",
        ]
        return names[dt.weekday()]

    # -----------------------------------------------------------------
    # Briefing-Generierung
    # -----------------------------------------------------------------

    async def generate_daily(self) -> str:
        """Generate the daily morning briefing message."""
        now = datetime.now(tz=self.tz)
        weekday = self._weekday_de(now)
        date_str = now.strftime("%d.%m.%Y")

        # Tages-Events: von jetzt bis Ende des Tages
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start.replace(hour=23, minute=59, second=59)
        events = await self._get_events_for_range(day_start, day_end)

        # Offene Tasks (alle, nicht nur heute fällige)
        tasks = await self._get_open_tasks()
        overdue = await self._get_overdue_tasks()

        # Tasks die heute fällig sind
        today_str = now.strftime("%Y-%m-%d")
        tasks_today = []
        tasks_upcoming = []
        tasks_no_date = []
        for t in tasks:
            if "due_date" in t:
                due_date_str = t["due_date"][:10]
                if due_date_str == today_str:
                    tasks_today.append(t)
                elif t not in overdue:
                    tasks_upcoming.append(t)
            else:
                tasks_no_date.append(t)

        # --- Nachricht zusammenbauen ---
        lines = [f"☀️ *Guten Morgen!* {weekday}, {date_str}", ""]

        # Termine
        if events:
            lines.append(f"📅 *Termine heute* ({len(events)})")
            for e in events:
                lines.append(self._format_event(e))
            lines.append("")
        else:
            lines.append("📅 Keine Termine heute.")
            lines.append("")

        # Überfällige Tasks
        if overdue:
            lines.append(f"⚠️ *Überfällig* ({len(overdue)})")
            for t in overdue:
                lines.append(self._format_task(t))
            lines.append("")

        # Heute fällige Tasks
        if tasks_today:
            lines.append(f"✅ *Heute fällig* ({len(tasks_today)})")
            for t in tasks_today:
                lines.append(self._format_task(t))
            lines.append("")

        # Zusammenfassung offene Tasks
        total_open = len(tasks)
        if total_open > 0 and not tasks_today and not overdue:
            lines.append(f"📋 {total_open} offene Aufgabe(n)")
            lines.append("")
        elif total_open > len(tasks_today) + len(overdue):
            remaining = total_open - len(tasks_today) - len(overdue)
            lines.append(f"📋 +{remaining} weitere offene Aufgabe(n)")
            lines.append("")

        # Abschluss
        lines.append("Schönen Tag! 👋")

        return "\n".join(lines)

    async def generate_weekly(self) -> str:
        """Generate the weekly overview message (sent on Mondays, Mo-Fr only)."""
        now = datetime.now(tz=self.tz)
        week_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        # Mo-Fr = 5 Tage (Arbeitswoche)
        week_end = week_start + timedelta(days=4, hours=23, minutes=59, seconds=59)
        date_range = (
            f"{week_start.strftime('%d.%m.')} – {week_end.strftime('%d.%m.%Y')}"
        )

        events = await self._get_events_for_range(week_start, week_end)
        tasks = await self._get_open_tasks()

        # Events nach Tag gruppieren
        events_by_day: dict[str, list[dict]] = {}
        for e in events:
            dt = e["dtstart"]
            local_dt = dt.astimezone(self.tz) if dt.tzinfo else dt
            day_key = local_dt.strftime("%Y-%m-%d")
            events_by_day.setdefault(day_key, []).append(e)

        # --- Nachricht zusammenbauen ---
        lines = [
            f"📋 *Wochenübersicht* — {date_range}",
            "",
        ]

        # Mo-Fr (5 Tage)
        for i in range(5):
            day = week_start + timedelta(days=i)
            day_key = day.strftime("%Y-%m-%d")
            day_name = self._weekday_de(day)
            day_date = day.strftime("%d.%m.")
            day_events = events_by_day.get(day_key, [])

            if day_events:
                lines.append(f"*{day_name} {day_date}*")
                for e in day_events:
                    lines.append(self._format_event(e))
                lines.append("")
            else:
                lines.append(f"*{day_name} {day_date}* — frei")
                lines.append("")

        # Tasks-Zusammenfassung (kompakt)
        total_open = len(tasks)
        if total_open > 0:
            # Tasks mit Fälligkeit diese Woche
            tasks_this_week = []
            for t in tasks:
                if "due_date" in t:
                    try:
                        due = datetime.fromisoformat(
                            t["due_date"].replace("Z", "+00:00")
                        )
                        if week_start <= due <= week_end:
                            tasks_this_week.append(t)
                    except (ValueError, TypeError):
                        pass

            lines.append(f"📋 *Offene Aufgaben:* {total_open}")
            if tasks_this_week:
                lines.append(
                    f"  ↳ davon {len(tasks_this_week)} diese Woche fällig"
                )
            lines.append("")

        lines.append("Gute Woche! 💪")

        return "\n".join(lines)
```

---

## 4. Scheduler-Integration

### 4.1 Briefing-Funktion für den Scheduler

Neue Datei: `src/niles/jobs/briefing.py`

```python
"""Scheduled briefing jobs."""

import logging

logger = logging.getLogger(__name__)


async def send_daily_briefing(app_state) -> None:
    """Generate and send the daily briefing via WhatsApp.

    Called by APScheduler. Accesses app.state for dependencies.
    """
    settings = app_state.settings
    if not settings.briefing_whatsapp_number:
        logger.warning("Briefing: Keine WhatsApp-Nummer konfiguriert")
        return

    briefing = app_state.briefing_generator
    whatsapp = app_state.whatsapp_action

    try:
        message = await briefing.generate_daily()
        await whatsapp.send_message(
            to=settings.briefing_whatsapp_number,
            text=message,
        )
        logger.info("Daily briefing sent to %s", settings.briefing_whatsapp_number)
    except Exception:
        logger.exception("Failed to send daily briefing")


async def send_weekly_briefing(app_state) -> None:
    """Generate and send the weekly briefing via WhatsApp.

    Called by APScheduler on Mondays, before the daily briefing.
    """
    settings = app_state.settings
    if not settings.briefing_whatsapp_number:
        logger.warning("Briefing: Keine WhatsApp-Nummer konfiguriert")
        return

    briefing = app_state.briefing_generator
    whatsapp = app_state.whatsapp_action

    try:
        message = await briefing.generate_weekly()
        await whatsapp.send_message(
            to=settings.briefing_whatsapp_number,
            text=message,
        )
        logger.info("Weekly briefing sent to %s", settings.briefing_whatsapp_number)
    except Exception:
        logger.exception("Failed to send weekly briefing")
```

### 4.2 Scheduler-Registrierung in `main.py`

Nach der bestehenden Scheduler-Konfiguration (Calendar Sync etc.):

```python
from niles.actions.briefing import BriefingGenerator
from niles.jobs.briefing import send_daily_briefing, send_weekly_briefing

# Briefing Generator
briefing_generator = BriefingGenerator(
    pool=pool,
    timezone=settings.timezone,
    vikunja_api_url=getattr(settings, "vikunja_api_url", ""),
    vikunja_api_token=getattr(settings, "vikunja_api_token", ""),
)
app.state.briefing_generator = briefing_generator

# Tägliches Briefing: Mo-Fr um briefing_daily_time (default 07:30)
if settings.feature_briefing_daily and settings.briefing_whatsapp_number:
    hour, minute = _parse_briefing_time(settings.briefing_daily_time)
    scheduler.add_job(
        send_daily_briefing,
        "cron",
        args=[app.state],
        day_of_week="mon-fri",
        hour=hour,
        minute=minute,
        id="briefing_daily",
        max_instances=1,
        misfire_grace_time=600,
        timezone=settings.timezone,
    )
    logger.info(
        "Daily briefing scheduled Mo-Fr at %02d:%02d for %s",
        hour, minute, settings.briefing_whatsapp_number,
    )

# Wöchentliche Übersicht: Montag um briefing_weekly_time (default 07:15)
if settings.feature_briefing_weekly and settings.briefing_whatsapp_number:
    hour, minute = _parse_briefing_time(settings.briefing_weekly_time)
    scheduler.add_job(
        send_weekly_briefing,
        "cron",
        args=[app.state],
        day_of_week="mon",
        hour=hour,
        minute=minute,
        id="briefing_weekly",
        max_instances=1,
        misfire_grace_time=600,
        timezone=settings.timezone,
    )
    logger.info(
        "Weekly briefing scheduled Mon at %02d:%02d for %s",
        hour, minute, settings.briefing_whatsapp_number,
    )
```

### 4.3 Hilfsfunktion für Zeitparsing

In `main.py` (oder in ein utils-Modul):

```python
def _parse_briefing_time(time_str: str) -> tuple[int, int]:
    """Parse 'HH:MM' string to (hour, minute) tuple."""
    try:
        parts = time_str.strip().split(":")
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
        return hour, minute
    except (ValueError, IndexError):
        logger.warning(
            "Ungültige Briefing-Zeit '%s', verwende 07:30", time_str
        )
        return 7, 30
```

---

## 5. Erweiterung `config/soul.md`

Folgender Abschnitt wird ergänzt (z.B. nach "### Aufgaben"):

```markdown
### Briefing / Tagesübersicht

- Niles sendet automatisch eine Morgen-Übersicht via WhatsApp (wenn konfiguriert).
- Wenn der Benutzer nach einer Tagesübersicht fragt ("Was steht heute an?", "Mein Tag", "Briefing"), rufe `find_event` für heute UND `list_tasks` auf und fasse die Ergebnisse zusammen.
- Wenn der Benutzer nach einer Wochenübersicht fragt ("Was steht diese Woche an?", "Wochenplan"), rufe `find_event` mit date_from=Montag und date_to=Sonntag auf UND `list_tasks`.
- Die automatischen Briefings werden NICHT über das LLM generiert. Wenn der Benutzer im Chat fragt, nutze die Tools.
```

---

## 6. Settings-UI Erweiterung (optional)

In `settings.html` einen neuen Abschnitt "Briefing":

```html
<!-- Briefing-Einstellungen -->
<div class="space-y-4">
  <h3 class="text-lg font-semibold">📋 Briefing</h3>

  <!-- Feature Toggles -->
  <label class="flex items-center gap-2">
    <input type="checkbox" name="feature_briefing_daily"
           hx-post="/ui/api/settings/feature_briefing_daily"
           hx-trigger="change"
           {{ "checked" if settings.feature_briefing_daily }}>
    Tägliches Briefing (Mo–Fr)
  </label>

  <label class="flex items-center gap-2">
    <input type="checkbox" name="feature_briefing_weekly"
           hx-post="/ui/api/settings/feature_briefing_weekly"
           hx-trigger="change"
           {{ "checked" if settings.feature_briefing_weekly }}>
    Wöchentliche Übersicht (Montag)
  </label>

  <!-- Uhrzeiten -->
  <div class="grid grid-cols-2 gap-4">
    <div>
      <label class="text-sm">Tagesbriefing (Mo–Fr)</label>
      <input type="time" name="briefing_daily_time"
             value="{{ settings.briefing_daily_time }}"
             hx-post="/ui/api/settings/briefing_daily_time"
             hx-trigger="change">
    </div>
    <div>
      <label class="text-sm">Wochenübersicht (Mo)</label>
      <input type="time" name="briefing_weekly_time"
             value="{{ settings.briefing_weekly_time }}"
             hx-post="/ui/api/settings/briefing_weekly_time"
             hx-trigger="change">
    </div>
  </div>

  <!-- WhatsApp-Nummer -->
  <div>
    <label class="text-sm">WhatsApp-Nummer (eigene)</label>
    <input type="text" name="briefing_whatsapp_number"
           value="{{ settings.briefing_whatsapp_number }}"
           placeholder="436601234567"
           hx-post="/ui/api/settings/briefing_whatsapp_number"
           hx-trigger="change">
  </div>
</div>
```

**Hinweis:** Scheduler-Jobs werden erst beim nächsten Neustart wirksam wenn die Settings geändert werden. Für Hot-Reload müsste der Scheduler dynamisch Jobs hinzufügen/entfernen — das ist ein optionaler Folgeschritt.

---

## 7. Beispiel-Output

### Tägliches Briefing (Mittwoch, 07:30)

```
☀️ *Guten Morgen!* Mittwoch, 26.02.2026

📅 *Termine heute* (3)
• 09:00 — Standup Team
• 12:30 — Mittagessen mit Julia 📍 Figlmüller
• 16:00 — Zahnarzt Dr. Weber 📍 Josefstädter Str. 42

⚠️ *Überfällig* (1)
• 🔴 Steuererklärung abgeben (fällig: 20.02.)

✅ *Heute fällig* (2)
• ⬆️ Präsentation fertigstellen (fällig: 26.02.)
• Milch kaufen (fällig: 26.02.)

📋 +4 weitere offene Aufgabe(n)

Schönen Tag! 👋
```

### Wöchentliche Übersicht (Montag, 07:15)

```
📋 *Wochenübersicht* — 24.02. – 28.02.2026

*Montag 24.02.*
• 09:00 — Standup Team
• 14:00 — Projekt-Review

*Dienstag 25.02.* — frei

*Mittwoch 26.02.*
• 12:30 — Mittagessen mit Julia 📍 Figlmüller
• 16:00 — Zahnarzt Dr. Weber

*Donnerstag 27.02.*
• 10:00 — Padel mit Max 📍 Padel City

*Freitag 28.02.*
• 09:00 — Standup Team

📋 *Offene Aufgaben:* 7
  ↳ davon 3 diese Woche fällig

Gute Woche! 💪
```

**Hinweis:** Die Wochenübersicht zeigt Mo–Fr (Arbeitswoche). Wochenend-Termine
werden nicht angezeigt, da kein Briefing am Wochenende gesendet wird.

---

## 8. Ablauf (Montag morgens)

```
07:15  APScheduler → send_weekly_briefing()
       ├── BriefingGenerator.generate_weekly()
       │   ├── SELECT events WHERE dtstart BETWEEN Mo 00:00 AND Fr 23:59
       │   ├── GET /api/v1/tasks/all?filter=done=false (Zusammenfassung)
       │   └── Format → Termine nach Tagen (Mo–Fr)
       └── WhatsAppAction.send_message(to=eigene_nummer)

07:30  APScheduler → send_daily_briefing()
       ├── BriefingGenerator.generate_daily()
       │   ├── SELECT events WHERE dtstart BETWEEN heute 00:00 AND 23:59
       │   ├── GET /api/v1/tasks/all?filter=done=false
       │   └── Format → Heutige Termine + fällige/überfällige Tasks
       └── WhatsAppAction.send_message(to=eigene_nummer)
```

**Di–Fr:** Nur das tägliche Briefing um 07:30.
**Sa–So:** Kein Briefing.

---

## 9. Verifikation

- [ ] `FEATURE_BRIEFING_DAILY=true` + Nummer gesetzt → Job mit `day_of_week=mon-fri` im Log
- [ ] `FEATURE_BRIEFING_WEEKLY=true` → Job mit `day_of_week=mon` im Log
- [ ] Tägliches Briefing um 07:30 enthält heutige Termine + fällige/überfällige Tasks
- [ ] Wöchentliches Briefing um 07:15 zeigt Mo–Fr mit Terminen pro Tag
- [ ] Am Wochenende kommt kein Briefing
- [ ] Montags kommen ZWEI Nachrichten: 07:15 Woche, 07:30 Tag
- [ ] Di–Fr kommt nur das Tagesbriefing um 07:30
- [ ] Wochenübersicht zeigt nur Mo–Fr (keine Sa/So)
- [ ] Tage ohne Termine zeigen "— frei"
- [ ] Ganztags-Termine zeigen "ganztägig" statt Uhrzeit
- [ ] Überfällige Tasks mit ⚠️ markiert (im Tagesbriefing)
- [ ] Wochenübersicht zeigt Tasks nur als kompakte Zusammenfassung
- [ ] WhatsApp-Nachricht kommt auf eigener Nummer an
- [ ] Ohne konfigurierte Nummer: Warning im Log, kein Crash
- [ ] Ohne Vikunja: Briefing wird trotzdem gesendet (nur Kalender, keine Tasks)
- [ ] Ohne Kalender-Events: "Keine Termine heute" statt leere Liste
- [ ] `BRIEFING_DAILY_TIME` und `BRIEFING_WEEKLY_TIME` sind separat konfigurierbar
- [ ] `python -m pytest tests/ -v` → alle Tests bestehen

---

## 10. Dateien-Übersicht

| Aktion | Datei |
|--------|-------|
| **Neu** | `src/niles/actions/briefing.py` |
| **Neu** | `src/niles/jobs/briefing.py` |
| Ändern | `src/niles/config.py` (5 neue Felder) |
| Ändern | `src/niles/settings_store.py` (EDITABLE_SETTINGS) |
| Ändern | `src/niles/main.py` (BriefingGenerator init, Scheduler-Jobs) |
| Ändern | `config/soul.md` (Briefing-Abschnitt) |
| Ändern | `.env.example` (5 neue Variablen) |
| Optional | `src/niles/templates/settings.html` (Briefing-UI) |
| **Neu** | `tests/test_briefing.py` |

---

## 11. Abgrenzung

| Was | Wie |
|-----|-----|
| Automatisches Morgen-Briefing | Template-basiert, kein LLM, APScheduler |
| "Was steht heute an?" im Chat | Agent ruft `find_event` + `list_tasks` auf (LLM) |
| Briefing-Uhrzeit ändern | Settings-UI oder .env, erfordert Neustart |
| Hot-Reload der Briefing-Zeit | Nicht in v1 (Folgeschritt: Scheduler dynamisch aktualisieren) |