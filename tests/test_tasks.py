"""Tests for Vikunja TasksAction."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from niles.actions.tasks import TasksAction

# --- Sample API Responses ---

SAMPLE_PROJECTS = [
    {"id": 1, "title": "Inbox"},
    {"id": 2, "title": "Arbeit"},
]

SAMPLE_TASKS = [
    {
        "id": 10,
        "title": "Milch kaufen",
        "done": False,
        "due_date": "2026-02-25T18:00:00Z",
        "priority": 0,
        "description": "",
        "project_id": 1,
    },
    {
        "id": 11,
        "title": "Steuererklärung",
        "done": False,
        "due_date": "0001-01-01T00:00:00Z",
        "priority": 3,
        "description": "Frist beachten",
        "project_id": 1,
    },
    {
        "id": 12,
        "title": "Report schreiben",
        "done": False,
        "due_date": "2026-03-01T09:00:00Z",
        "priority": 2,
        "description": "",
        "project_id": 2,
    },
]

SAMPLE_TASKS_WITH_DONE = SAMPLE_TASKS + [
    {
        "id": 13,
        "title": "Einkauf erledigt",
        "done": True,
        "due_date": "0001-01-01T00:00:00Z",
        "priority": 0,
        "description": "",
        "project_id": 1,
    },
]

SAMPLE_CREATED_TASK = {
    "id": 20,
    "title": "Zahnarzt anrufen",
    "done": False,
    "project_id": 1,
}


# --- Helpers ---


def _mock_client_for(responses: list[MagicMock]):
    """Create a mock httpx.AsyncClient that returns responses in sequence."""
    mock_client = AsyncMock()
    # Each call to get/put/post returns next response
    side_effects = list(responses)

    def _make_response(json_data, status_code=200):
        resp = MagicMock()
        resp.json.return_value = json_data
        resp.status_code = status_code
        resp.raise_for_status = MagicMock()
        return resp

    if isinstance(responses[0], MagicMock):
        # Already MagicMock responses
        mock_client.get = AsyncMock(side_effect=side_effects)
        mock_client.put = AsyncMock(side_effect=side_effects)
        mock_client.post = AsyncMock(side_effect=side_effects)
    return mock_client


def _resp(json_data):
    """Create a mock httpx response."""
    resp = MagicMock()
    resp.json.return_value = json_data
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    return resp


@pytest.fixture
def action():
    return TasksAction(
        api_url="http://vikunja:3456/api/v1",
        api_token="test-token",
    )


def _patch_client(mock_client):
    """Patch httpx.AsyncClient as async context manager."""
    patcher = patch("niles.actions.tasks.httpx.AsyncClient")
    mock_cls = patcher.start()
    mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
    return patcher


# --- Tests ---


class TestListTasks:
    async def test_empty_list(self, action):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_resp([]))

        with patch("niles.actions.tasks.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await action.list_tasks()

        assert result == []

    async def test_returns_simplified(self, action):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_resp(SAMPLE_TASKS))

        with patch("niles.actions.tasks.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await action.list_tasks()

        assert len(result) == 3
        # First task: has due_date, no priority
        assert result[0]["title"] == "Milch kaufen"
        assert result[0]["due_date"] == "2026-02-25T18:00:00Z"
        assert "priority" not in result[0]
        # Second task: no due_date (zero value filtered), has priority
        assert result[1]["title"] == "Steuererklärung"
        assert "due_date" not in result[1]
        assert result[1]["priority"] == "hoch"
        assert result[1]["description"] == "Frist beachten"
        # Third task: has both
        assert result[2]["title"] == "Report schreiben"
        assert result[2]["priority"] == "mittel"

    async def test_filter_done(self, action):
        """When include_done=False, the filter param is sent to API."""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_resp(SAMPLE_TASKS))

        with patch("niles.actions.tasks.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            await action.list_tasks(include_done=False)

        # Verify filter param was passed
        call_kwargs = mock_client.get.call_args
        assert call_kwargs.kwargs["params"]["filter"] == "done = false"

    async def test_include_done(self, action):
        """When include_done=True, no filter param is sent."""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_resp(SAMPLE_TASKS_WITH_DONE))

        with patch("niles.actions.tasks.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await action.list_tasks(include_done=True)

        call_kwargs = mock_client.get.call_args
        assert "filter" not in call_kwargs.kwargs["params"]
        assert len(result) == 4

    async def test_filter_by_project(self, action):
        """Filter tasks by project name."""
        mock_client = AsyncMock()
        # First call: list tasks, second call: find project
        mock_client.get = AsyncMock(
            side_effect=[_resp(SAMPLE_TASKS), _resp(SAMPLE_PROJECTS)]
        )

        with patch("niles.actions.tasks.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await action.list_tasks(project="Arbeit")

        assert len(result) == 1
        assert result[0]["title"] == "Report schreiben"

    async def test_filter_by_unknown_project(self, action):
        """Unknown project returns empty list."""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            side_effect=[_resp(SAMPLE_TASKS), _resp(SAMPLE_PROJECTS)]
        )

        with patch("niles.actions.tasks.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await action.list_tasks(project="Nonexistent")

        assert result == []


class TestCreateTask:
    async def test_minimal(self, action):
        """Create task with only title."""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_resp(SAMPLE_PROJECTS))
        mock_client.put = AsyncMock(return_value=_resp(SAMPLE_CREATED_TASK))

        with patch("niles.actions.tasks.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await action.create_task(title="Zahnarzt anrufen")

        assert result["created"] is True
        assert result["title"] == "Zahnarzt anrufen"
        assert result["id"] == 20
        # Verify PUT was called with correct payload
        put_call = mock_client.put.call_args
        assert put_call.kwargs["json"]["title"] == "Zahnarzt anrufen"
        assert "description" not in put_call.kwargs["json"]
        assert "priority" not in put_call.kwargs["json"]

    async def test_full_params(self, action):
        """Create task with all parameters."""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_resp(SAMPLE_PROJECTS))
        mock_client.put = AsyncMock(return_value=_resp(SAMPLE_CREATED_TASK))

        with patch("niles.actions.tasks.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await action.create_task(
                title="Report",
                description="Monatsbericht",
                due_date="2026-03-01T09:00",
                priority=3,
                project="Arbeit",
            )

        assert result["created"] is True
        put_call = mock_client.put.call_args
        payload = put_call.kwargs["json"]
        assert payload["title"] == "Report"
        assert payload["description"] == "Monatsbericht"
        assert payload["priority"] == 3
        assert "due_date" in payload
        # Verify project lookup matched "Arbeit" → project 2
        assert "/projects/2/tasks" in put_call.args[0]

    async def test_unknown_project(self, action):
        """Unknown project returns error."""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_resp(SAMPLE_PROJECTS))

        with patch("niles.actions.tasks.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await action.create_task(
                title="Test", project="Nonexistent"
            )

        assert "error" in result
        assert "Nonexistent" in result["error"]

    async def test_no_projects_available(self, action):
        """No projects at all returns error."""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_resp([]))

        with patch("niles.actions.tasks.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await action.create_task(title="Test")

        assert "error" in result

    async def test_priority_capped_at_4(self, action):
        """Priority values above 4 are capped."""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_resp(SAMPLE_PROJECTS))
        mock_client.put = AsyncMock(return_value=_resp(SAMPLE_CREATED_TASK))

        with patch("niles.actions.tasks.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            await action.create_task(title="Urgent", priority=10)

        put_call = mock_client.put.call_args
        assert put_call.kwargs["json"]["priority"] == 4

    async def test_priority_as_string(self, action):
        """Priority passed as string (common with local LLMs) is coerced to int."""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_resp(SAMPLE_PROJECTS))
        mock_client.put = AsyncMock(return_value=_resp(SAMPLE_CREATED_TASK))

        with patch("niles.actions.tasks.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            await action.create_task(title="Test", priority="3")

        put_call = mock_client.put.call_args
        assert put_call.kwargs["json"]["priority"] == 3

    async def test_priority_zero_string_excluded(self, action):
        """Priority '0' as string should not be included in payload."""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_resp(SAMPLE_PROJECTS))
        mock_client.put = AsyncMock(return_value=_resp(SAMPLE_CREATED_TASK))

        with patch("niles.actions.tasks.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            await action.create_task(title="Test", priority="0")

        put_call = mock_client.put.call_args
        assert "priority" not in put_call.kwargs["json"]

    async def test_due_date_date_only(self, action):
        """Date-only due_date gets midnight UTC appended."""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_resp(SAMPLE_PROJECTS))
        mock_client.put = AsyncMock(return_value=_resp(SAMPLE_CREATED_TASK))

        with patch("niles.actions.tasks.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            await action.create_task(title="Test", due_date="2026-02-24")

        put_call = mock_client.put.call_args
        assert put_call.kwargs["json"]["due_date"] == "2026-02-24T00:00:00Z"

    async def test_due_date_with_time(self, action):
        """Datetime due_date without seconds gets normalized."""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_resp(SAMPLE_PROJECTS))
        mock_client.put = AsyncMock(return_value=_resp(SAMPLE_CREATED_TASK))

        with patch("niles.actions.tasks.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            await action.create_task(title="Test", due_date="2026-02-24T14:00")

        put_call = mock_client.put.call_args
        assert put_call.kwargs["json"]["due_date"] == "2026-02-24T14:00:00Z"

    async def test_due_date_already_utc(self, action):
        """Due date ending with Z is passed through unchanged."""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_resp(SAMPLE_PROJECTS))
        mock_client.put = AsyncMock(return_value=_resp(SAMPLE_CREATED_TASK))

        with patch("niles.actions.tasks.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            await action.create_task(title="Test", due_date="2026-02-24T14:00:00Z")

        put_call = mock_client.put.call_args
        assert put_call.kwargs["json"]["due_date"] == "2026-02-24T14:00:00Z"


class TestCompleteTask:
    async def test_found_and_completed(self, action):
        """Task found by title and marked as done."""
        mock_client = AsyncMock()
        # First call: list_tasks (GET /tasks/all), second call: POST to complete
        mock_client.get = AsyncMock(return_value=_resp(SAMPLE_TASKS))
        mock_client.post = AsyncMock(return_value=_resp({"done": True}))

        with patch("niles.actions.tasks.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await action.complete_task(title="Milch")

        assert result["completed"] is True
        assert result["title"] == "Milch kaufen"
        # Verify POST was to correct task ID
        post_call = mock_client.post.call_args
        assert "/tasks/10" in post_call.args[0]
        assert post_call.kwargs["json"]["done"] is True

    async def test_not_found(self, action):
        """No matching task returns error."""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_resp(SAMPLE_TASKS))

        with patch("niles.actions.tasks.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await action.complete_task(title="Nonexistent")

        assert "error" in result
        assert "Nonexistent" in result["error"]

    async def test_ambiguous(self, action):
        """Multiple matching tasks returns error with matches."""
        # Two tasks that both contain "e"
        tasks_with_overlap = [
            {"id": 1, "title": "Einkaufen", "done": False,
             "due_date": "0001-01-01T00:00:00Z", "priority": 0,
             "description": "", "project_id": 1},
            {"id": 2, "title": "Email schreiben", "done": False,
             "due_date": "0001-01-01T00:00:00Z", "priority": 0,
             "description": "", "project_id": 1},
        ]
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_resp(tasks_with_overlap))

        with patch("niles.actions.tasks.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await action.complete_task(title="e")

        assert "error" in result
        assert "matches" in result
        assert len(result["matches"]) == 2


class TestDefaultProject:
    async def test_caches_default_project(self, action):
        """Default project ID is cached after first call."""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_resp(SAMPLE_PROJECTS))
        mock_client.put = AsyncMock(return_value=_resp(SAMPLE_CREATED_TASK))

        with patch("niles.actions.tasks.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            # First call populates cache
            pid = await action._get_default_project_id()
            assert pid == 1

            # Second call uses cache (no additional HTTP call)
            pid2 = await action._get_default_project_id()
            assert pid2 == 1

        # GET /projects was only called once (cached)
        assert mock_client.get.call_count == 1


class TestInit:
    def test_strips_trailing_slash(self):
        action = TasksAction(
            api_url="http://vikunja:3456/api/v1/",
            api_token="tok",
        )
        assert action.api_url == "http://vikunja:3456/api/v1"

    def test_sets_auth_header(self):
        action = TasksAction(api_url="http://x", api_token="my-token")
        assert action.headers["Authorization"] == "Bearer my-token"
