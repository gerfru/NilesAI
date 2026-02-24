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
    # Data queries
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

    def _filter_overdue(self, tasks: list[dict]) -> list[dict]:
        """Filter tasks that are past their due date (pure filter, no API call)."""
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
    # Formatting
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
    # Briefing generation
    # -----------------------------------------------------------------

    async def generate_daily(self) -> str:
        """Generate the daily morning briefing message."""
        now = datetime.now(tz=self.tz)
        weekday = self._weekday_de(now)
        date_str = now.strftime("%d.%m.%Y")

        # Day events: full day range
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start.replace(hour=23, minute=59, second=59)
        events = await self._get_events_for_range(day_start, day_end)

        # Open tasks (all, not just today) — single API call
        tasks = await self._get_open_tasks()
        overdue = self._filter_overdue(tasks)

        # Tasks due today (compare in local timezone, not UTC string slicing)
        today_date = now.date()
        tasks_today = []
        for t in tasks:
            if "due_date" in t:
                try:
                    due = datetime.fromisoformat(
                        t["due_date"].replace("Z", "+00:00")
                    )
                    if due.astimezone(self.tz).date() == today_date:
                        tasks_today.append(t)
                except (ValueError, TypeError):
                    pass

        # --- Build message ---
        lines = [f"☀️ *Guten Morgen!* {weekday}, {date_str}", ""]

        # Events
        if events:
            lines.append(f"📅 *Termine heute* ({len(events)})")
            for e in events:
                lines.append(self._format_event(e))
            lines.append("")
        else:
            lines.append("📅 Keine Termine heute.")
            lines.append("")

        # Overdue tasks
        if overdue:
            lines.append(f"⚠️ *Überfällig* ({len(overdue)})")
            for t in overdue:
                lines.append(self._format_task(t))
            lines.append("")

        # Tasks due today
        if tasks_today:
            lines.append(f"✅ *Heute fällig* ({len(tasks_today)})")
            for t in tasks_today:
                lines.append(self._format_task(t))
            lines.append("")

        # Summary of open tasks
        total_open = len(tasks)
        if total_open > 0 and not tasks_today and not overdue:
            lines.append(f"📋 {total_open} offene Aufgabe(n)")
            lines.append("")
        elif total_open > len(tasks_today) + len(overdue):
            remaining = total_open - len(tasks_today) - len(overdue)
            lines.append(f"📋 +{remaining} weitere offene Aufgabe(n)")
            lines.append("")

        # Closing
        lines.append("Schönen Tag! 👋")

        return "\n".join(lines)

    async def generate_weekly(self) -> str:
        """Generate the weekly overview message (sent on Mondays, Mo-Fr only)."""
        now = datetime.now(tz=self.tz)
        week_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        # Mo-Fr = 5 days (work week)
        week_end = week_start + timedelta(days=4, hours=23, minutes=59, seconds=59)
        date_range = (
            f"{week_start.strftime('%d.%m.')} – {week_end.strftime('%d.%m.%Y')}"
        )

        events = await self._get_events_for_range(week_start, week_end)
        tasks = await self._get_open_tasks()

        # Group events by day
        events_by_day: dict[str, list[dict]] = {}
        for e in events:
            dt = e["dtstart"]
            local_dt = dt.astimezone(self.tz) if dt.tzinfo else dt
            day_key = local_dt.strftime("%Y-%m-%d")
            events_by_day.setdefault(day_key, []).append(e)

        # --- Build message ---
        lines = [
            f"📋 *Wochenübersicht* — {date_range}",
            "",
        ]

        # Mo-Fr (5 days)
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

        # Tasks summary (compact)
        total_open = len(tasks)
        if total_open > 0:
            # Tasks due this week
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
