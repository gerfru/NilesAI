"""Vikunja task management actions."""

import logging
from datetime import datetime

import httpx

logger = logging.getLogger(__name__)


class TasksAction:
    """Interface to Vikunja REST API for task management."""

    def __init__(
        self,
        api_url: str,
        api_token: str,
        client: httpx.AsyncClient | None = None,
    ):
        self.api_url = api_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {api_token}"}
        self._default_project_id: int | None = None
        self._client = client or httpx.AsyncClient(timeout=10)

    async def _get_default_project_id(self) -> int | None:
        """Get the first available project ID (cached)."""
        if self._default_project_id is not None:
            return self._default_project_id
        resp = await self._client.get(
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
        resp = await self._client.get(
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
        # Vikunja API: GET /api/v1/tasks/all
        # Note: limited to 50 tasks (no pagination). Users with more
        # tasks should use the Vikunja Web-UI for the full list.
        params = {
            "sort_by": "due_date",
            "order_by": "asc",
            "per_page": 50,
        }
        if not include_done:
            params["filter"] = "done = false"

        resp = await self._client.get(
            f"{self.api_url}/tasks",
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
            # Normalize to full ISO datetime for Vikunja API.
            # Uses datetime.fromisoformat() to robustly handle all formats:
            # "2026-02-24", "2026-02-24T14:00", "2026-02-24T14:00:30",
            # "2026-02-24T14:00:00Z", "2026-02-24T14:00:00+02:00"
            try:
                dt = datetime.fromisoformat(due_date.replace("Z", "+00:00"))
                payload["due_date"] = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            except ValueError:
                logger.warning("Unparseable due_date '%s', passing as-is", due_date)
                payload["due_date"] = due_date
        # LLMs sometimes pass priority as string
        try:
            priority = int(priority)
        except (TypeError, ValueError):
            priority = 0
        if priority > 0:
            payload["priority"] = min(priority, 4)

        resp = await self._client.put(
            f"{self.api_url}/projects/{project_id}/tasks",
            headers=self.headers,
            json=payload,
            timeout=10,
        )
        if resp.status_code >= 400:
            logger.error(
                "Vikunja create_task %s: %s", resp.status_code, resp.text[:200]
            )
            return {
                "error": f"Aufgabe konnte nicht erstellt werden (HTTP {resp.status_code})"
            }
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

        matches = [t for t in tasks if title_lower in t["title"].lower()]

        if not matches:
            return {"error": f"Keine offene Aufgabe gefunden: '{title}'"}
        if len(matches) > 1:
            titles = [m["title"] for m in matches[:5]]
            return {
                "error": "Mehrere Aufgaben gefunden. Welche meinst du?",
                "matches": titles,
            }

        task_id = matches[0]["id"]
        resp = await self._client.post(
            f"{self.api_url}/tasks/{task_id}",
            headers=self.headers,
            json={"done": True},
            timeout=10,
        )
        resp.raise_for_status()

        return {"completed": True, "title": matches[0]["title"]}
