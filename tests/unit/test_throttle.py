"""
Unit tests for bot/middlewares/throttle.py
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.middlewares.throttle import (
    check_spam,
    increment_spam_counter,
    ThrottleMiddleware,
    SPAM_LIMIT,
    SPAM_TTL,
    _spam_key,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_redis(get_value=None):
    """Return an AsyncMock Redis client with configurable get() return value."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=get_value)
    redis.incr = AsyncMock(return_value=1)
    redis.expire = AsyncMock(return_value=True)
    return redis


# ---------------------------------------------------------------------------
# _spam_key
# ---------------------------------------------------------------------------

def test_spam_key_format():
    assert _spam_key(123456) == "spam:123456"
    assert _spam_key(0) == "spam:0"


# ---------------------------------------------------------------------------
# check_spam
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_check_spam_no_key_allows():
    """No key in Redis → user is allowed."""
    redis = make_redis(get_value=None)
    assert await check_spam(redis, 1) is True


@pytest.mark.asyncio
async def test_check_spam_below_limit_allows():
    """Counter below limit → user is allowed."""
    for count in range(SPAM_LIMIT):  # 0, 1, 2
        redis = make_redis(get_value=str(count).encode())
        assert await check_spam(redis, 1) is True


@pytest.mark.asyncio
async def test_check_spam_at_limit_blocks():
    """Counter == SPAM_LIMIT → user is blocked."""
    redis = make_redis(get_value=str(SPAM_LIMIT).encode())
    assert await check_spam(redis, 1) is False


@pytest.mark.asyncio
async def test_check_spam_above_limit_blocks():
    """Counter > SPAM_LIMIT → user is blocked."""
    redis = make_redis(get_value=str(SPAM_LIMIT + 5).encode())
    assert await check_spam(redis, 1) is False


@pytest.mark.asyncio
async def test_check_spam_uses_correct_key():
    """check_spam must query the correct Redis key."""
    redis = make_redis(get_value=None)
    telegram_id = 99999
    await check_spam(redis, telegram_id)
    redis.get.assert_awaited_once_with(_spam_key(telegram_id))


# ---------------------------------------------------------------------------
# increment_spam_counter
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_increment_sets_ttl_on_first_call():
    """First increment (incr returns 1) must set TTL."""
    redis = make_redis()
    redis.incr = AsyncMock(return_value=1)

    result = await increment_spam_counter(redis, 42)

    assert result == 1
    redis.expire.assert_awaited_once_with(_spam_key(42), SPAM_TTL)


@pytest.mark.asyncio
async def test_increment_no_ttl_on_subsequent_calls():
    """Subsequent increments must NOT reset TTL."""
    redis = make_redis()
    redis.incr = AsyncMock(return_value=2)

    await increment_spam_counter(redis, 42)

    redis.expire.assert_not_awaited()


@pytest.mark.asyncio
async def test_increment_returns_new_value():
    redis = make_redis()
    redis.incr = AsyncMock(return_value=3)
    result = await increment_spam_counter(redis, 7)
    assert result == 3


# ---------------------------------------------------------------------------
# ThrottleMiddleware
# ---------------------------------------------------------------------------

def make_message(telegram_id: int | None = 100):
    msg = AsyncMock()
    if telegram_id is not None:
        msg.from_user = MagicMock()
        msg.from_user.id = telegram_id
    else:
        msg.from_user = None
    msg.answer = AsyncMock()
    return msg


@pytest.mark.asyncio
async def test_middleware_allows_user_below_limit():
    """User below limit → handler is called."""
    redis = make_redis(get_value=b"1")  # count=1 < 3
    middleware = ThrottleMiddleware(redis)

    handler = AsyncMock(return_value="ok")
    msg = make_message(telegram_id=1)

    result = await middleware(handler, msg, {})

    handler.assert_awaited_once()
    assert result == "ok"


@pytest.mark.asyncio
async def test_middleware_blocks_user_at_limit():
    """User at limit → handler is NOT called, limit message sent."""
    redis = make_redis(get_value=str(SPAM_LIMIT).encode())
    middleware = ThrottleMiddleware(redis)

    handler = AsyncMock()
    msg = make_message(telegram_id=2)

    await middleware(handler, msg, {})

    handler.assert_not_awaited()
    msg.answer.assert_awaited_once_with(ThrottleMiddleware.LIMIT_MESSAGE)


@pytest.mark.asyncio
async def test_middleware_allows_no_from_user():
    """If from_user is None, middleware should not block."""
    redis = make_redis(get_value=None)
    middleware = ThrottleMiddleware(redis)

    handler = AsyncMock(return_value="ok")
    msg = make_message(telegram_id=None)

    result = await middleware(handler, msg, {})

    handler.assert_awaited_once()
    assert result == "ok"


@pytest.mark.asyncio
async def test_middleware_passes_data_to_handler():
    """Middleware must forward the data dict to the handler unchanged."""
    redis = make_redis(get_value=b"0")
    middleware = ThrottleMiddleware(redis)

    handler = AsyncMock(return_value=None)
    msg = make_message(telegram_id=5)
    data = {"key": "value"}

    await middleware(handler, msg, data)

    handler.assert_awaited_once_with(msg, data)
