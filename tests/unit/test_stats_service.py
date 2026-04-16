"""Unit tests for StatsService."""
from datetime import datetime, timedelta

import pytest

from bot.models.models import Category, Status
from bot.repositories.request_repo import create_request, update_status
from bot.repositories.user_repo import get_or_create_user
from bot.services.stats_service import StatsResult, StatsService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _make_user(session, telegram_id: int = 1):
    return await get_or_create_user(session, telegram_id=telegram_id, username="tester")


async def _make_request(session, user_id: int, **kwargs):
    defaults = dict(
        category=Category.LOST,
        description="A lost dog near the park",
        location={"latitude": 50.4, "longitude": 30.5, "address_text": "Kyiv"},
        contact="@tester",
    )
    defaults.update(kwargs)
    return await create_request(session, user_id=user_id, **defaults)


# ---------------------------------------------------------------------------
# StatsResult dataclass
# ---------------------------------------------------------------------------

def test_stats_result_fields():
    result = StatsResult(
        total=5,
        by_category={Category.LOST: 3, Category.INJURED: 2},
        by_status={Status.NEW: 4, Status.DONE: 1},
        today=2,
        week=4,
        month=5,
    )
    assert result.total == 5
    assert result.by_category[Category.LOST] == 3
    assert result.by_status[Status.NEW] == 4
    assert result.today == 2
    assert result.week == 4
    assert result.month == 5


# ---------------------------------------------------------------------------
# Empty database
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_stats_empty_db(session):
    svc = StatsService(session)
    result = await svc.get_stats()

    assert isinstance(result, StatsResult)
    assert result.total == 0
    assert result.today == 0
    assert result.week == 0
    assert result.month == 0
    # All categories and statuses should be present with 0 counts
    for cat in Category:
        assert result.by_category[cat] == 0
    for status in Status:
        assert result.by_status[status] == 0


# ---------------------------------------------------------------------------
# Total count
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_stats_total(session):
    user = await _make_user(session)
    await _make_request(session, user_id=user.id)
    await _make_request(session, user_id=user.id)
    await _make_request(session, user_id=user.id)

    svc = StatsService(session)
    result = await svc.get_stats()
    assert result.total == 3


# ---------------------------------------------------------------------------
# By category
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_stats_by_category(session):
    user = await _make_user(session)
    await _make_request(session, user_id=user.id, category=Category.LOST)
    await _make_request(session, user_id=user.id, category=Category.LOST)
    await _make_request(session, user_id=user.id, category=Category.INJURED)
    await _make_request(session, user_id=user.id, category=Category.DEAD)

    svc = StatsService(session)
    result = await svc.get_stats()

    assert result.by_category[Category.LOST] == 2
    assert result.by_category[Category.INJURED] == 1
    assert result.by_category[Category.DEAD] == 1
    assert result.by_category[Category.STERILIZATION] == 0


@pytest.mark.asyncio
async def test_get_stats_by_category_all_present(session):
    """All Category keys must be present in by_category even with zero counts."""
    user = await _make_user(session)
    await _make_request(session, user_id=user.id, category=Category.LOST)

    svc = StatsService(session)
    result = await svc.get_stats()

    assert set(result.by_category.keys()) == set(Category)


# ---------------------------------------------------------------------------
# By status
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_stats_by_status(session):
    user = await _make_user(session)
    req1 = await _make_request(session, user_id=user.id)
    req2 = await _make_request(session, user_id=user.id)
    await _make_request(session, user_id=user.id)

    await update_status(session, req1.id, Status.IN_PROGRESS)
    await update_status(session, req2.id, Status.IN_PROGRESS)
    await update_status(session, req2.id, Status.DONE)

    svc = StatsService(session)
    result = await svc.get_stats()

    assert result.by_status[Status.NEW] == 1
    assert result.by_status[Status.IN_PROGRESS] == 1
    assert result.by_status[Status.DONE] == 1
    assert result.by_status[Status.REJECTED] == 0


@pytest.mark.asyncio
async def test_get_stats_by_status_all_present(session):
    """All Status keys must be present in by_status even with zero counts."""
    svc = StatsService(session)
    result = await svc.get_stats()
    assert set(result.by_status.keys()) == set(Status)


# ---------------------------------------------------------------------------
# Time-based counts (today / week / month)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_stats_today_counts_recent_request(session):
    user = await _make_user(session)
    await _make_request(session, user_id=user.id)

    svc = StatsService(session)
    result = await svc.get_stats()

    # A freshly created request must appear in today's count
    assert result.today >= 1


@pytest.mark.asyncio
async def test_get_stats_week_includes_today(session):
    user = await _make_user(session)
    await _make_request(session, user_id=user.id)

    svc = StatsService(session)
    result = await svc.get_stats()

    assert result.week >= result.today


@pytest.mark.asyncio
async def test_get_stats_month_includes_week(session):
    user = await _make_user(session)
    await _make_request(session, user_id=user.id)

    svc = StatsService(session)
    result = await svc.get_stats()

    assert result.month >= result.week


@pytest.mark.asyncio
async def test_get_stats_total_equals_sum_by_category(session):
    user = await _make_user(session)
    await _make_request(session, user_id=user.id, category=Category.LOST)
    await _make_request(session, user_id=user.id, category=Category.INJURED)
    await _make_request(session, user_id=user.id, category=Category.DEAD)

    svc = StatsService(session)
    result = await svc.get_stats()

    assert result.total == sum(result.by_category.values())


@pytest.mark.asyncio
async def test_get_stats_total_equals_sum_by_status(session):
    user = await _make_user(session)
    await _make_request(session, user_id=user.id)
    await _make_request(session, user_id=user.id)

    svc = StatsService(session)
    result = await svc.get_stats()

    assert result.total == sum(result.by_status.values())
