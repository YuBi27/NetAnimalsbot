"""Unit tests for RequestService (task 8.1)."""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from bot.models.models import Base, Category, MediaType, Status, User
from bot.repositories import request_repo, user_repo
from bot.services.request_service import RequestService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as s:
        yield s

    await engine.dispose()


@pytest_asyncio.fixture
async def user(session):
    u = await user_repo.get_or_create_user(session, telegram_id=100, username="testuser")
    await session.commit()
    return u


@pytest.fixture
def mock_bot():
    bot = AsyncMock()
    bot.send_message = AsyncMock()
    bot.send_photo = AsyncMock()
    return bot


@pytest_asyncio.fixture
async def service(session, mock_bot):
    return RequestService(session=session, bot=mock_bot)


# ---------------------------------------------------------------------------
# create_request
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_request_returns_request_with_new_status(service, user):
    req = await service.create_request(
        user_id=user.id,
        category=Category.LOST,
        description="A lost dog near the park",
        location={"address_text": "Main St"},
        media_files=None,
        contact="@owner",
    )
    assert req.id is not None
    assert req.status == Status.NEW
    assert req.category == Category.LOST
    assert req.description == "A lost dog near the park"


@pytest.mark.asyncio
async def test_create_request_attaches_media(service, user):
    media_files = [
        {"file_id": "photo_abc", "type": "photo"},
        {"file_id": "video_xyz", "type": "video"},
    ]
    req = await service.create_request(
        user_id=user.id,
        category=Category.INJURED,
        description="Injured cat on the road",
        location={"latitude": 50.0, "longitude": 30.0},
        media_files=media_files,
        contact=None,
    )
    assert len(req.media) == 2
    file_ids = {m.file_id for m in req.media}
    assert "photo_abc" in file_ids
    assert "video_xyz" in file_ids


@pytest.mark.asyncio
async def test_create_request_no_media(service, user):
    req = await service.create_request(
        user_id=user.id,
        category=Category.STERILIZATION,
        description="Cat needs sterilization",
        location=None,
        media_files=[],
        contact=None,
    )
    assert req.media == []


# ---------------------------------------------------------------------------
# change_status
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_change_status_valid_transition(service, user, mock_bot):
    req = await service.create_request(
        user_id=user.id,
        category=Category.LOST,
        description="Lost parrot in the garden",
        location=None,
        media_files=None,
        contact=None,
    )
    updated = await service.change_status(req.id, Status.IN_PROGRESS)
    assert updated.status == Status.IN_PROGRESS


@pytest.mark.asyncio
async def test_change_status_invalid_transition_raises(service, user):
    req = await service.create_request(
        user_id=user.id,
        category=Category.LOST,
        description="Lost parrot in the garden",
        location=None,
        media_files=None,
        contact=None,
    )
    with pytest.raises(ValueError):
        await service.change_status(req.id, Status.DONE)  # NEW → DONE not allowed


@pytest.mark.asyncio
async def test_change_status_notifies_user(service, user, mock_bot):
    req = await service.create_request(
        user_id=user.id,
        category=Category.INJURED,
        description="Injured bird found",
        location=None,
        media_files=None,
        contact=None,
    )
    await service.change_status(req.id, Status.IN_PROGRESS)
    mock_bot.send_message.assert_awaited_once()
    call_kwargs = mock_bot.send_message.call_args
    assert call_kwargs.kwargs["chat_id"] == user.telegram_id


@pytest.mark.asyncio
async def test_change_status_nonexistent_request_raises(service):
    with pytest.raises(ValueError):
        await service.change_status(9999, Status.IN_PROGRESS)


# ---------------------------------------------------------------------------
# get_user_requests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_user_requests_returns_all(service, user):
    for desc in ["First request about a dog", "Second request about a cat"]:
        await service.create_request(
            user_id=user.id,
            category=Category.LOST,
            description=desc,
            location=None,
            media_files=None,
            contact=None,
        )
    requests = await service.get_user_requests(user.telegram_id)
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_get_user_requests_unknown_user_returns_empty(service):
    result = await service.get_user_requests(telegram_id=99999)
    assert result == []


# ---------------------------------------------------------------------------
# publish_to_channel
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_publish_to_channel_injured(service, user, mock_bot):
    req = await service.create_request(
        user_id=user.id,
        category=Category.INJURED,
        description="Injured dog on the street",
        location={"address_text": "Oak Ave"},
        media_files=None,
        contact=None,
    )
    await service.publish_to_channel(req, channel_id="-100123456")
    mock_bot.send_message.assert_awaited_once()
    assert mock_bot.send_message.call_args.kwargs["chat_id"] == "-100123456"


@pytest.mark.asyncio
async def test_publish_to_channel_lost(service, user, mock_bot):
    req = await service.create_request(
        user_id=user.id,
        category=Category.LOST,
        description="Lost golden retriever near park",
        location=None,
        media_files=None,
        contact=None,
    )
    await service.publish_to_channel(req, channel_id="-100123456")
    mock_bot.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_publish_to_channel_skips_non_publishable(service, user, mock_bot):
    for cat in (Category.STERILIZATION, Category.DEAD):
        mock_bot.reset_mock()
        req = await service.create_request(
            user_id=user.id,
            category=cat,
            description="Some description here",
            location=None,
            media_files=None,
            contact=None,
        )
        await service.publish_to_channel(req, channel_id="-100123456")
        mock_bot.send_message.assert_not_awaited()
        mock_bot.send_photo.assert_not_awaited()


@pytest.mark.asyncio
async def test_publish_to_channel_sends_photo_when_available(service, user, mock_bot):
    req = await service.create_request(
        user_id=user.id,
        category=Category.INJURED,
        description="Injured cat with photo",
        location=None,
        media_files=[{"file_id": "photo_001", "type": "photo"}],
        contact=None,
    )
    await service.publish_to_channel(req, channel_id="-100123456")
    mock_bot.send_photo.assert_awaited_once()
    mock_bot.send_message.assert_not_awaited()


# ---------------------------------------------------------------------------
# notify_user_status_change
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_notify_user_status_change_sends_message(service, user, mock_bot):
    req = await service.create_request(
        user_id=user.id,
        category=Category.LOST,
        description="Lost hamster in the yard",
        location=None,
        media_files=None,
        contact=None,
    )
    await service.notify_user_status_change(req, user_telegram_id=user.telegram_id)
    mock_bot.send_message.assert_awaited_once()
    text = mock_bot.send_message.call_args.kwargs["text"]
    assert str(req.id) in text


@pytest.mark.asyncio
async def test_notify_user_status_change_swallows_bot_error(service, user, mock_bot):
    mock_bot.send_message.side_effect = Exception("Telegram API error")
    req = await service.create_request(
        user_id=user.id,
        category=Category.LOST,
        description="Lost hamster in the yard",
        location=None,
        media_files=None,
        contact=None,
    )
    # Should not raise
    await service.notify_user_status_change(req, user_telegram_id=user.telegram_id)
