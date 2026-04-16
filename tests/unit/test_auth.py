"""
Unit tests for bot/middlewares/auth.py
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from bot.middlewares.auth import is_admin, AdminAuthMiddleware


# ---------------------------------------------------------------------------
# is_admin
# ---------------------------------------------------------------------------

def test_is_admin_matching_id():
    assert is_admin(123456, 123456) is True


def test_is_admin_non_matching_id():
    assert is_admin(111111, 999999) is False


def test_is_admin_zero_ids():
    assert is_admin(0, 0) is True


def test_is_admin_negative_id_no_match():
    assert is_admin(-1, 123) is False


# ---------------------------------------------------------------------------
# AdminAuthMiddleware
# ---------------------------------------------------------------------------

def _make_message(telegram_id: int | None) -> MagicMock:
    """Build a minimal fake aiogram Message."""
    message = MagicMock()
    message.answer = AsyncMock()
    if telegram_id is None:
        message.from_user = None
    else:
        message.from_user = MagicMock()
        message.from_user.id = telegram_id
    return message


@pytest.mark.asyncio
async def test_middleware_allows_admin():
    admin_id = 42
    middleware = AdminAuthMiddleware(admin_id=admin_id)
    handler = AsyncMock(return_value="ok")
    message = _make_message(telegram_id=admin_id)

    result = await middleware(handler, message, {})

    handler.assert_awaited_once_with(message, {})
    message.answer.assert_not_called()
    assert result == "ok"


@pytest.mark.asyncio
async def test_middleware_blocks_non_admin():
    admin_id = 42
    middleware = AdminAuthMiddleware(admin_id=admin_id)
    handler = AsyncMock()
    message = _make_message(telegram_id=99999)

    result = await middleware(handler, message, {})

    handler.assert_not_awaited()
    message.answer.assert_awaited_once_with("Немає доступу")
    assert result is None


@pytest.mark.asyncio
async def test_middleware_blocks_no_from_user():
    """Message with no from_user (e.g. channel post) must be blocked."""
    admin_id = 42
    middleware = AdminAuthMiddleware(admin_id=admin_id)
    handler = AsyncMock()
    message = _make_message(telegram_id=None)

    result = await middleware(handler, message, {})

    handler.assert_not_awaited()
    assert result is None


@pytest.mark.asyncio
async def test_middleware_passes_data_dict_to_handler():
    """Extra data dict must be forwarded to the handler unchanged."""
    admin_id = 7
    middleware = AdminAuthMiddleware(admin_id=admin_id)
    handler = AsyncMock(return_value=None)
    message = _make_message(telegram_id=admin_id)
    data = {"session": object(), "state": object()}

    await middleware(handler, message, data)

    handler.assert_awaited_once_with(message, data)
