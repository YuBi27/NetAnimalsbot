"""Unit tests for bot/repositories/media_repo.py"""
import itertools

import pytest

from bot.models.models import Category, MediaType, Request, Status, User
from bot.repositories.media_repo import add_media, count_media, get_media_by_request


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_id_counter = itertools.count(start=1000)


async def _make_request(session) -> Request:
    user = User(telegram_id=next(_id_counter), username="tester")
    session.add(user)
    await session.flush()

    req = Request(
        user_id=user.id,
        category=Category.LOST,
        description="A lost dog near the park",
        status=Status.NEW,
    )
    session.add(req)
    await session.flush()
    return req


# ---------------------------------------------------------------------------
# add_media
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_add_media_returns_media_object(session):
    req = await _make_request(session)
    media = await add_media(session, req.id, "file_abc", MediaType.PHOTO)

    assert media.id is not None
    assert media.request_id == req.id
    assert media.file_id == "file_abc"
    assert media.type == MediaType.PHOTO


@pytest.mark.asyncio
async def test_add_media_video_type(session):
    req = await _make_request(session)
    media = await add_media(session, req.id, "vid_001", MediaType.VIDEO)

    assert media.type == MediaType.VIDEO


@pytest.mark.asyncio
async def test_add_media_up_to_five_allowed(session):
    req = await _make_request(session)
    for i in range(5):
        await add_media(session, req.id, f"file_{i}", MediaType.PHOTO)

    assert await count_media(session, req.id) == 5


@pytest.mark.asyncio
async def test_add_media_sixth_raises(session):
    req = await _make_request(session)
    for i in range(5):
        await add_media(session, req.id, f"file_{i}", MediaType.PHOTO)

    with pytest.raises(ValueError, match="limit is 5"):
        await add_media(session, req.id, "file_extra", MediaType.PHOTO)


# ---------------------------------------------------------------------------
# get_media_by_request
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_media_by_request_empty(session):
    req = await _make_request(session)
    result = await get_media_by_request(session, req.id)
    assert result == []


@pytest.mark.asyncio
async def test_get_media_by_request_returns_all(session):
    req = await _make_request(session)
    await add_media(session, req.id, "f1", MediaType.PHOTO)
    await add_media(session, req.id, "f2", MediaType.VIDEO)

    result = await get_media_by_request(session, req.id)
    assert len(result) == 2
    file_ids = {m.file_id for m in result}
    assert file_ids == {"f1", "f2"}


@pytest.mark.asyncio
async def test_get_media_by_request_isolation(session):
    """Media from one request must not appear in another request's results."""
    req1 = await _make_request(session)
    req2 = await _make_request(session)

    await add_media(session, req1.id, "req1_file", MediaType.PHOTO)

    assert await get_media_by_request(session, req2.id) == []


# ---------------------------------------------------------------------------
# count_media
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_count_media_zero_initially(session):
    req = await _make_request(session)
    assert await count_media(session, req.id) == 0


@pytest.mark.asyncio
async def test_count_media_increments(session):
    req = await _make_request(session)
    for i in range(3):
        await add_media(session, req.id, f"f{i}", MediaType.PHOTO)
        assert await count_media(session, req.id) == i + 1
