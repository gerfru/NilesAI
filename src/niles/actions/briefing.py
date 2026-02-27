"""Daily and weekly briefing generator."""

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import asyncpg
import httpx

logger = logging.getLogger(__name__)

# Priority labels (matching Vikunja convention)
_PRIORITY = {1: "⬇️", 2: "➡️", 3: "⬆️", 4: "🔴"}

_OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

# WMO Weather interpretation codes → German descriptions
# https://open-meteo.com/en/docs#weathervariables
_WEATHER_CODES: dict[int, str] = {
    0: "Klar",
    1: "Ueberwiegend klar",
    2: "Teilweise bewoelkt",
    3: "Bedeckt",
    45: "Nebel",
    48: "Nebel mit Reifbildung",
    51: "Leichter Nieselregen",
    53: "Maessiger Nieselregen",
    55: "Starker Nieselregen",
    56: "Leichter gefrierender Nieselregen",
    57: "Starker gefrierender Nieselregen",
    61: "Leichter Regen",
    63: "Maessiger Regen",
    65: "Starker Regen",
    66: "Leichter gefrierender Regen",
    67: "Starker gefrierender Regen",
    71: "Leichter Schneefall",
    73: "Maessiger Schneefall",
    75: "Starker Schneefall",
    77: "Schneegriesel",
    80: "Leichte Regenschauer",
    81: "Maessige Regenschauer",
    82: "Starke Regenschauer",
    85: "Leichte Schneeschauer",
    86: "Starke Schneeschauer",
    95: "Gewitter",
    96: "Gewitter mit leichtem Hagel",
    99: "Gewitter mit starkem Hagel",
}

_WEEKDAYS_SHORT = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


class BriefingGenerator:
    """Generates formatted briefing messages from calendar + tasks + weather."""

    def __init__(
        self,
        pool: asyncpg.Pool,
        timezone: str = "Europe/Vienna",
        vikunja_store=None,
        weather_latitude: str = "",
        weather_longitude: str = "",
    ):
        self.pool = pool
        self.tz = ZoneInfo(timezone)
        self.timezone = timezone
        self.vikunja_store = vikunja_store
        self.weather_latitude = weather_latitude
        self.weather_longitude = weather_longitude

    # -----------------------------------------------------------------
    # Data queries
    # -----------------------------------------------------------------

    async def _get_events_for_range(
        self,
        date_from: datetime,
        date_to: datetime,
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

    async def _get_open_tasks(self, user_id: int | None = None) -> list[dict]:
        """Fetch open tasks from Vikunja API using per-user credentials.

        Returns simplified task list, or empty list if Vikunja
        is not configured or not reachable.
        """
        if not self.vikunja_store or user_id is None:
            return []

        creds = await self.vikunja_store.get_credentials(user_id)
        if not creds or not creds["api_token"]:
            return []

        api_url = creds["api_url"].rstrip("/") if creds["api_url"] else ""
        if not api_url:
            return []

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{api_url}/tasks/all",
                    headers={"Authorization": f"Bearer {creds['api_token']}"},
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
                    due = datetime.fromisoformat(t["due_date"].replace("Z", "+00:00"))
                    if due < now:
                        overdue.append(t)
                except (ValueError, TypeError):
                    pass
        return overdue

    # -----------------------------------------------------------------
    # Weather
    # -----------------------------------------------------------------

    async def _fetch_daily_weather(self, days: int) -> dict | None:
        """Fetch daily weather data from Open-Meteo. Returns parsed dict or None."""
        if not self.weather_latitude or not self.weather_longitude:
            return None

        params = {
            "latitude": self.weather_latitude,
            "longitude": self.weather_longitude,
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max",
            "timezone": self.timezone,
            "forecast_days": str(days),
        }
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(_OPEN_METEO_URL, params=params)
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            logger.warning("Briefing: Wetter nicht abrufbar: %s", e)
            return None

        daily = data.get("daily", {})
        if not daily.get("time"):
            return None
        return daily

    @staticmethod
    def _daily_value(daily: dict, key: str, index: int, default="?"):
        """Safely get a value from Open-Meteo daily data arrays."""
        values = daily.get(key) or []
        return values[index] if index < len(values) else default

    async def _get_weather_today(self) -> str | None:
        """Fetch today's weather from Open-Meteo. Returns formatted string or None."""
        daily = await self._fetch_daily_weather(days=1)
        if not daily:
            return None

        code = self._daily_value(daily, "weather_code", 0, default=0)
        t_min = self._daily_value(daily, "temperature_2m_min", 0)
        t_max = self._daily_value(daily, "temperature_2m_max", 0)
        precip = self._daily_value(daily, "precipitation_sum", 0, default=0)
        prob = self._daily_value(daily, "precipitation_probability_max", 0, default=0)

        desc = _WEATHER_CODES.get(code, f"Unbekannt ({code})")
        line = f"🌤 *Wetter heute:* {desc}, {t_min}–{t_max}°C"
        if precip and float(precip) > 0:
            line += f", {precip}mm Niederschlag ({prob}%)"
        elif prob and int(prob) > 20:
            line += f", Regenwahrscheinlichkeit {prob}%"
        return line

    async def _get_weather_forecast(self, days: int = 5) -> list[str] | None:
        """Fetch multi-day forecast from Open-Meteo. Returns formatted lines or None."""
        daily = await self._fetch_daily_weather(days=days)
        if not daily:
            return None

        dates = daily["time"]
        lines = ["🌤 *Wetter*"]
        for i, date_str in enumerate(dates):
            try:
                dt = datetime.fromisoformat(date_str)
                day_label = f"{_WEEKDAYS_SHORT[dt.weekday()]} {dt.strftime('%d.%m.')}"
            except (ValueError, TypeError):
                day_label = date_str

            code = self._daily_value(daily, "weather_code", i, default=0)
            t_min = self._daily_value(daily, "temperature_2m_min", i)
            t_max = self._daily_value(daily, "temperature_2m_max", i)
            precip = self._daily_value(daily, "precipitation_sum", i, default=0)
            prob = self._daily_value(
                daily, "precipitation_probability_max", i, default=0
            )

            desc = _WEATHER_CODES.get(code, f"Unbekannt ({code})")
            detail = f"  {day_label}: {desc}, {t_min}–{t_max}°C"
            if precip and float(precip) > 0:
                detail += f", {precip}mm ({prob}%)"
            elif prob and int(prob) > 20:
                detail += f", Regen {prob}%"
            lines.append(detail)

        return lines

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
                due = datetime.fromisoformat(task["due_date"].replace("Z", "+00:00"))
                local_due = due.astimezone(self.tz)
                line += f" (fällig: {local_due.strftime('%d.%m.')})"
            except (ValueError, TypeError):
                pass
        return line

    def _weekday_de(self, dt: datetime) -> str:
        """Return German weekday name."""
        names = [
            "Montag",
            "Dienstag",
            "Mittwoch",
            "Donnerstag",
            "Freitag",
            "Samstag",
            "Sonntag",
        ]
        return names[dt.weekday()]

    # -----------------------------------------------------------------
    # Briefing generation
    # -----------------------------------------------------------------

    async def generate_daily(self, user_id: int | None = None) -> str:
        """Generate the daily morning briefing message."""
        now = datetime.now(tz=self.tz)
        weekday = self._weekday_de(now)
        date_str = now.strftime("%d.%m.%Y")

        # Day events: full day range
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start.replace(hour=23, minute=59, second=59)
        events = await self._get_events_for_range(day_start, day_end)

        # Open tasks (all, not just today) — single API call, per-user
        tasks = await self._get_open_tasks(user_id)
        overdue = self._filter_overdue(tasks)

        # Tasks due today (compare in local timezone, not UTC string slicing)
        # Exclude tasks already in overdue to avoid duplication
        overdue_ids = {t["id"] for t in overdue}
        today_date = now.date()
        tasks_today = []
        for t in tasks:
            if t["id"] in overdue_ids:
                continue
            if "due_date" in t:
                try:
                    due = datetime.fromisoformat(t["due_date"].replace("Z", "+00:00"))
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

        # Weather
        weather_line = await self._get_weather_today()
        if weather_line:
            lines.append(weather_line)
            lines.append("")

        # Closing
        lines.append("Schönen Tag! 👋")

        return "\n".join(lines)

    async def generate_weekly(self, user_id: int | None = None) -> str:
        """Generate the weekly overview message (sent on Mondays, Mo-Fr only)."""
        now = datetime.now(tz=self.tz)
        week_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        # Mo-Fr = 5 days (work week)
        week_end = week_start + timedelta(days=4, hours=23, minutes=59, seconds=59)
        date_range = (
            f"{week_start.strftime('%d.%m.')} – {week_end.strftime('%d.%m.%Y')}"
        )

        events = await self._get_events_for_range(week_start, week_end)
        tasks = await self._get_open_tasks(user_id)

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
                lines.append(f"  ↳ davon {len(tasks_this_week)} diese Woche fällig")
            lines.append("")

        # Weather forecast (Mo-Fr = 5 days)
        weather_lines = await self._get_weather_forecast(days=5)
        if weather_lines:
            lines.extend(weather_lines)
            lines.append("")

        lines.append("Gute Woche! 💪")

        return "\n".join(lines)
