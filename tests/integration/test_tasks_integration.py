"""Integration tests for TasksAction (Vikunja API)."""

import httpx
import pytest
import pytest_asyncio

from niles.actions.tasks import TasksAction

from .conftest import VIKUNJA_API_TOKEN, VIKUNJA_API_URL

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]


@pytest_asyncio.fixture(loop_scope="session")
async def tasks_action(vikunja_available):
    """TasksAction connected to real Vikunja (via Caddy, self-signed TLS)."""
    client = httpx.AsyncClient(timeout=10, verify=False)
    action = TasksAction(
        api_url=VIKUNJA_API_URL,
        api_token=VIKUNJA_API_TOKEN,
        client=client,
    )
    yield action
    await client.aclose()


class TestVikunjaIntegration:
    async def test_list_tasks(self, tasks_action):
        result = await tasks_action.list_tasks()
        assert isinstance(result, list)

    async def test_create_and_complete_task(self, tasks_action):
        # Create
        result = await tasks_action.create_task(
            title="[TEST] Integration Test Task",
            description="Created by integration test, safe to delete",
        )
        assert result.get("created") is True
        assert result.get("id") is not None
        task_title = result["title"]

        # Verify it appears in list
        tasks = await tasks_action.list_tasks()
        found = [t for t in tasks if t["title"] == task_title]
        assert len(found) == 1

        # Complete
        complete_result = await tasks_action.complete_task(title=task_title)
        assert complete_result.get("completed") is True

        # Verify no longer in open tasks
        tasks_after = await tasks_action.list_tasks(include_done=False)
        still_open = [t for t in tasks_after if t["title"] == task_title]
        assert len(still_open) == 0

    async def test_create_task_with_due_date(self, tasks_action):
        result = await tasks_action.create_task(
            title="[TEST] Task with Due Date",
            due_date="2026-12-31T23:59:00Z",
        )
        assert result.get("created") is True
        # Cleanup
        await tasks_action.complete_task(title="[TEST] Task with Due Date")
