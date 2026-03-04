"""Integration tests for CalendarAction (PostgreSQL)."""

from datetime import datetime, timedelta, timezone

import pytest

from niles.actions.calendar import CalendarAction

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]


class TestFindEvent:
    async def test_find_by_keyword(self, pool_in_tx, seed_events):
        action = CalendarAction(pool_in_tx, timezone="Europe/Vienna")
        results = await action.find_by_query(query="Meeting")
        assert len(results) >= 1
        assert any("Meeting" in e["summary"] for e in results)

    async def test_find_by_date_range(self, pool_in_tx, seed_events):
        now = datetime.now(timezone.utc)
        action = CalendarAction(pool_in_tx, timezone="Europe/Vienna")
        results = await action.find_by_query(
            date_from=now.isoformat(),
            date_to=(now + timedelta(days=2)).isoformat(),
        )
        assert len(results) >= 1

    async def test_find_no_match(self, pool_in_tx, seed_events):
        action = CalendarAction(pool_in_tx, timezone="Europe/Vienna")
        results = await action.find_by_query(query="Nonexistent Event XYZ")
        assert results == []

    async def test_result_has_expected_keys(self, pool_in_tx, seed_events):
        action = CalendarAction(pool_in_tx, timezone="Europe/Vienna")
        results = await action.find_by_query(query="Meeting")
        assert len(results) >= 1
        event = results[0]
        assert "summary" in event
        assert "start" in event
        assert "all_day" in event

    async def test_relative_date_heute(self, pool_in_tx, seed_events):
        action = CalendarAction(pool_in_tx, timezone="Europe/Vienna")
        results = await action.find_by_query(date_from="heute")
        assert isinstance(results, list)

    async def test_relative_date_morgen(self, pool_in_tx, seed_events):
        action = CalendarAction(pool_in_tx, timezone="Europe/Vienna")
        results = await action.find_by_query(
            date_from="morgen",
            date_to="morgen",
        )
        assert len(results) >= 1
        assert any("Dentist" in e["summary"] for e in results)
