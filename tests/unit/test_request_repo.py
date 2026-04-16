from datetime import datetime, timedelta

import pytest

from bot.models.models import Category, Status
from bot.repositories.request_repo import (
    create_request,
    get_request_by_id,
    get_requests_filtered,
    get_user_requests,
    update_status,
)
from bot.repositories.user_repo import get_or_create_user


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _make_user(session, telegram_id: int = 1, username: str = "tester"):
    return await get_or_create_user(session, telegram_id=telegram_id, username=username)


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
# create_request
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_request_basic(session):
    user = await _make_user(session)
    req = await _make_request(session, user_id=user.id)

    assert req.id is not None
    assert req.status == Status.NEW
    assert req.category == Category.LOST
    assert req.latitude == 50.4
    assert req.longitude == 30.5
    assert req.address_text == "Kyiv"
    assert req.contact == "@tester"


@pytest.mark.asyncio
async def test_create_request_no_location(session):
    user = await _make_user(session)
    req = await create_request(
        session,
        user_id=user.id,
        category=Category.INJURED,
        description="Injured cat on the street",
        location=None,
        contact="+380991234567",
    )
    assert req.latitude is None
    assert req.longitude is None
    assert req.address_text is None
    assert req.contact == "+380991234567"


@pytest.mark.asyncio
async def test_create_request_partial_location(session):
    user = await _make_user(session)
    req = await create_request(
        session,
        user_id=user.id,
        category=Category.DEAD,
        description="Dead animal near road",
        location={"address_text": "Lviv, Shevchenko St"},
        contact=None,
    )
    assert req.address_text == "Lviv, Shevchenko St"
    assert req.latitude is None
    assert req.longitude is None


# ---------------------------------------------------------------------------
# get_request_by_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_request_by_id_found(session):
    user = await _make_user(session)
    req = await _make_request(session, user_id=user.id)

    fetched = await get_request_by_id(session, req.id)
    assert fetched is not None
    assert fetched.id == req.id


@pytest.mark.asyncio
async def test_get_request_by_id_not_found(session):
    result = await get_request_by_id(session, request_id=99999)
    assert result is None


# ---------------------------------------------------------------------------
# get_user_requests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_user_requests_empty(session):
    user = await _make_user(session)
    requests = await get_user_requests(session, user_id=user.id)
    assert requests == []


@pytest.mark.asyncio
async def test_get_user_requests_multiple(session):
    user = await _make_user(session)
    await _make_request(session, user_id=user.id, category=Category.LOST)
    await _make_request(session, user_id=user.id, category=Category.INJURED)

    requests = await get_user_requests(session, user_id=user.id)
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_get_user_requests_isolation(session):
    """Requests from one user must not appear in another user's list."""
    u1 = await _make_user(session, telegram_id=1)
    u2 = await _make_user(session, telegram_id=2)
    await _make_request(session, user_id=u1.id)

    assert await get_user_requests(session, user_id=u2.id) == []


# ---------------------------------------------------------------------------
# update_status
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_status_valid_transition(session):
    user = await _make_user(session)
    req = await _make_request(session, user_id=user.id)

    updated = await update_status(session, req.id, Status.IN_PROGRESS)
    assert updated.status == Status.IN_PROGRESS


@pytest.mark.asyncio
async def test_update_status_new_to_rejected(session):
    user = await _make_user(session)
    req = await _make_request(session, user_id=user.id)

    updated = await update_status(session, req.id, Status.REJECTED)
    assert updated.status == Status.REJECTED


@pytest.mark.asyncio
async def test_update_status_in_progress_to_done(session):
    user = await _make_user(session)
    req = await _make_request(session, user_id=user.id)
    await update_status(session, req.id, Status.IN_PROGRESS)

    updated = await update_status(session, req.id, Status.DONE)
    assert updated.status == Status.DONE


@pytest.mark.asyncio
async def test_update_status_invalid_transition_raises(session):
    user = await _make_user(session)
    req = await _make_request(session, user_id=user.id)

    with pytest.raises(ValueError, match="not allowed"):
        await update_status(session, req.id, Status.DONE)  # NEW → DONE is forbidden


@pytest.mark.asyncio
async def test_update_status_done_is_terminal(session):
    user = await _make_user(session)
    req = await _make_request(session, user_id=user.id)
    await update_status(session, req.id, Status.IN_PROGRESS)
    await update_status(session, req.id, Status.DONE)

    with pytest.raises(ValueError):
        await update_status(session, req.id, Status.REJECTED)


@pytest.mark.asyncio
async def test_update_status_not_found_raises(session):
    with pytest.raises(ValueError, match="not found"):
        await update_status(session, request_id=99999, new_status=Status.IN_PROGRESS)


# ---------------------------------------------------------------------------
# get_requests_filtered
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_requests_filtered_no_filters(session):
    user = await _make_user(session)
    await _make_request(session, user_id=user.id, category=Category.LOST)
    await _make_request(session, user_id=user.id, category=Category.DEAD)

    results = await get_requests_filtered(session)
    assert len(results) == 2


@pytest.mark.asyncio
async def test_get_requests_filtered_by_category(session):
    user = await _make_user(session)
    await _make_request(session, user_id=user.id, category=Category.LOST)
    await _make_request(session, user_id=user.id, category=Category.INJURED)

    results = await get_requests_filtered(session, category=Category.LOST)
    assert len(results) == 1
    assert results[0].category == Category.LOST


@pytest.mark.asyncio
async def test_get_requests_filtered_by_status(session):
    user = await _make_user(session)
    req = await _make_request(session, user_id=user.id)
    await update_status(session, req.id, Status.IN_PROGRESS)
    await _make_request(session, user_id=user.id)  # stays NEW

    results = await get_requests_filtered(session, status=Status.IN_PROGRESS)
    assert len(results) == 1
    assert results[0].status == Status.IN_PROGRESS


@pytest.mark.asyncio
async def test_get_requests_filtered_by_date_range(session):
    user = await _make_user(session)
    req = await _make_request(session, user_id=user.id)

    now = datetime.utcnow()
    results = await get_requests_filtered(
        session,
        date_from=now - timedelta(minutes=1),
        date_to=now + timedelta(minutes=1),
    )
    assert any(r.id == req.id for r in results)


@pytest.mark.asyncio
async def test_get_requests_filtered_date_excludes_old(session):
    user = await _make_user(session)
    await _make_request(session, user_id=user.id)

    future = datetime.utcnow() + timedelta(hours=1)
    results = await get_requests_filtered(session, date_from=future)
    assert results == []


@pytest.mark.asyncio
async def test_get_requests_filtered_combined(session):
    user = await _make_user(session)
    req1 = await _make_request(session, user_id=user.id, category=Category.LOST)
    await _make_request(session, user_id=user.id, category=Category.INJURED)
    await update_status(session, req1.id, Status.IN_PROGRESS)

    results = await get_requests_filtered(
        session, category=Category.LOST, status=Status.IN_PROGRESS
    )
    assert len(results) == 1
    assert results[0].id == req1.id
