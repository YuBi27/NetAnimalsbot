"""Unit tests for BroadcastService (task 8.5)."""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from bot.models.models import Base
from bot.repositories import user_repo
from bot.services.broadcast_service import BroadcastResult, BroadcastService


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


@pytest.fixture
def mock_bot():
    bot = AsyncMock()
    bot.send_message = AsyncMock()
    bot.send_photo = AsyncMock()
    bot.send_video = AsyncMock()
    return bot


@pytest_asyncio.fixture
async def service(session, mock_bot):
    return BroadcastService(session=session, bot=mock_bot)


@pytest_asyncio.fixture
async def three_users(session):
    users = []
    for i in range(3):
        u = await user_repo.get_or_create_user(
            session, telegram_id=1000 + i, username=f"user{i}"
        )
        users.append(u)
    await session.commit()
    return users


# ---------------------------------------------------------------------------
# BroadcastResult dataclass
# ---------------------------------------------------------------------------

def test_broadcast_result_fields():
    result = BroadcastResult(success_count=5, fail_count=2)
    assert result.success_count == 5
    assert result.fail_count == 2


# ---------------------------------------------------------------------------
# No users
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_broadcast_no_users_returns_zeros(service, mock_bot):
    result = await service.send_broadcast(text="Hello everyone")
    assert result.success_count == 0
    assert result.fail_count == 0
    mock_bot.send_message.assert_not_awaited()


# ---------------------------------------------------------------------------
# Text-only broadcast
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_broadcast_text_only(service, mock_bot, three_users):
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        result = await service.send_broadcast(text="Important announcement")

    assert result.success_count == 3
    assert result.fail_count == 0
    assert mock_bot.send_message.await_count == 3

    # Each call must target the correct chat_id
    called_ids = {call.kwargs["chat_id"] for call in mock_bot.send_message.call_args_list}
    assert called_ids == {1000, 1001, 1002}


# ---------------------------------------------------------------------------
# Photo broadcast
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_broadcast_with_photo(service, mock_bot, three_users):
    media = {"file_id": "photo_abc", "type": "photo"}
    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = await service.send_broadcast(text="Check this photo", media=media)

    assert result.success_count == 3
    assert result.fail_count == 0
    assert mock_bot.send_photo.await_count == 3
    mock_bot.send_message.assert_not_awaited()

    for call in mock_bot.send_photo.call_args_list:
        assert call.kwargs["photo"] == "photo_abc"
        assert call.kwargs["caption"] == "Check this photo"


# ---------------------------------------------------------------------------
# Video broadcast
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_broadcast_with_video(service, mock_bot, three_users):
    media = {"file_id": "video_xyz", "type": "video"}
    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = await service.send_broadcast(text="Watch this video", media=media)

    assert result.success_count == 3
    assert result.fail_count == 0
    assert mock_bot.send_video.await_count == 3
    mock_bot.send_message.assert_not_awaited()


# ---------------------------------------------------------------------------
# Throttle — asyncio.sleep(0.05) called between sends (Req 7.2)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_broadcast_throttle_called_for_each_user(service, mock_bot, three_users):
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await service.send_broadcast(text="Throttle test")

    # sleep must be called once per user
    assert mock_sleep.await_count == 3
    for call in mock_sleep.call_args_list:
        assert call.args[0] == 0.05


# ---------------------------------------------------------------------------
# Failure handling — Req 7.4
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_broadcast_continues_after_failure(service, mock_bot, three_users):
    """If one send fails, broadcast continues and fail_count is incremented."""
    call_count = 0

    async def flaky_send_message(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise Exception("Telegram API error")

    mock_bot.send_message.side_effect = flaky_send_message

    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = await service.send_broadcast(text="Flaky broadcast")

    assert result.success_count == 2
    assert result.fail_count == 1


@pytest.mark.asyncio
async def test_send_broadcast_all_fail(service, mock_bot, three_users):
    mock_bot.send_message.side_effect = Exception("Network error")

    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = await service.send_broadcast(text="All fail")

    assert result.success_count == 0
    assert result.fail_count == 3


# ---------------------------------------------------------------------------
# Unknown media type falls back to send_message
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_broadcast_unknown_media_type_falls_back_to_text(service, mock_bot, three_users):
    media = {"file_id": "doc_001", "type": "document"}
    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = await service.send_broadcast(text="Fallback test", media=media)

    assert result.success_count == 3
    assert mock_bot.send_message.await_count == 3
    mock_bot.send_photo.assert_not_awaited()
    mock_bot.send_video.assert_not_awaited()
