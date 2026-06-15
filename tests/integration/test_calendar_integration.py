"""Integration tests for CalendarAction (PostgreSQL)."""

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from niles.actions.calendar import CalendarAction
from niles.event_store import EventStore

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]


class TestFindEvent:
    async def test_find_by_keyword(self, pool_in_tx, seed_events, seed_user):
        action = CalendarAction(EventStore(pool_in_tx), timezone="Europe/Vienna")
        results = await action.find_by_query(query="Meeting", user_id=seed_user)
        assert len(results) >= 1
        assert any("Meeting" in e["summary"] for e in results)

    async def test_find_by_date_range(self, pool_in_tx, seed_events, seed_user):
        now = datetime.now(timezone.utc)
        action = CalendarAction(EventStore(pool_in_tx), timezone="Europe/Vienna")
        results = await action.find_by_query(
            date_from=now.isoformat(),
            date_to=(now + timedelta(days=2)).isoformat(),
            user_id=seed_user,
        )
        assert len(results) >= 1

    async def test_find_no_match(self, pool_in_tx, seed_events, seed_user):
        action = CalendarAction(EventStore(pool_in_tx), timezone="Europe/Vienna")
        results = await action.find_by_query(query="Nonexistent Event XYZ", user_id=seed_user)
        assert results == []

    async def test_result_has_expected_keys(self, pool_in_tx, seed_events, seed_user):
        action = CalendarAction(EventStore(pool_in_tx), timezone="Europe/Vienna")
        results = await action.find_by_query(query="Meeting", user_id=seed_user)
        assert len(results) >= 1
        event = results[0]
        assert "summary" in event
        assert "start" in event
        assert "all_day" in event

    async def test_relative_date_heute(self, pool_in_tx, seed_events, seed_user):
        action = CalendarAction(EventStore(pool_in_tx), timezone="Europe/Vienna")
        results = await action.find_by_query(date_from="heute", user_id=seed_user)
        assert isinstance(results, list)

    async def test_relative_date_morgen(self, pool_in_tx, seed_events, seed_user):
        action = CalendarAction(EventStore(pool_in_tx), timezone="Europe/Vienna")
        results = await action.find_by_query(
            date_from="morgen",
            date_to="morgen",
            user_id=seed_user,
        )
        assert len(results) >= 1
        assert any("Dentist" in e["summary"] for e in results)


class TestCrossUserIsolation:
    """Verify that user B cannot see user A's calendar events."""

    @pytest_asyncio.fixture(loop_scope="session")
    async def second_user(self, db_conn):
        """Insert a second test user."""
        return await db_conn.fetchval(
            """
            INSERT INTO users (email, display_name, auth_method, is_admin)
            VALUES ('other@example.com', 'Other User', 'password', false)
            RETURNING id
            """,
        )

    async def test_other_user_sees_no_events(self, pool_in_tx, seed_events, seed_user, second_user):
        """User B should not see user A's events."""
        action = CalendarAction(EventStore(pool_in_tx), timezone="Europe/Vienna")

        # User A sees their events
        results_a = await action.find_by_query(query="Meeting", user_id=seed_user)
        assert len(results_a) >= 1

        # User B sees nothing
        results_b = await action.find_by_query(query="Meeting", user_id=second_user)
        assert results_b == []

    async def test_other_user_date_range_isolated(self, pool_in_tx, seed_events, seed_user, second_user):
        """User B should not see user A's events even with a wide date range."""
        now = datetime.now(timezone.utc)
        action = CalendarAction(EventStore(pool_in_tx), timezone="Europe/Vienna")

        results_b = await action.find_by_query(
            date_from=(now - timedelta(days=1)).isoformat(),
            date_to=(now + timedelta(days=7)).isoformat(),
            user_id=second_user,
        )
        assert results_b == []
