"""
Throttle middleware — антиспам захист.

Redis key: spam:{telegram_id}
Ліміт: 3 заявки за останню годину (TTL 3600 сек).
"""

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message

SPAM_LIMIT = 3
SPAM_TTL = 3600  # seconds (1 hour)
SPAM_KEY_PREFIX = "spam"


def _spam_key(telegram_id: int) -> str:
    return f"{SPAM_KEY_PREFIX}:{telegram_id}"


async def check_spam(redis_client, telegram_id: int) -> bool:
    """
    Returns True if the user is allowed (count < SPAM_LIMIT).
    Returns False if the user is blocked (count >= SPAM_LIMIT).
    """
    key = _spam_key(telegram_id)
    value = await redis_client.get(key)
    if value is None:
        return True
    return int(value) < SPAM_LIMIT


async def increment_spam_counter(redis_client, telegram_id: int) -> int:
    """
    Increments the spam counter for the user.
    Sets TTL of SPAM_TTL seconds on first increment.
    Returns the new counter value.
    """
    key = _spam_key(telegram_id)
    new_value = await redis_client.incr(key)
    if new_value == 1:
        await redis_client.expire(key, SPAM_TTL)
    return new_value


class ThrottleMiddleware(BaseMiddleware):
    """
    aiogram 3.x middleware that blocks users who have submitted
    3 or more requests within the last hour.
    """

    LIMIT_MESSAGE = (
        "⛔ Ви перевищили ліміт заявок (3 на годину). "
        "Будь ласка, спробуйте пізніше."
    )

    def __init__(self, redis_client) -> None:
        self.redis = redis_client
        super().__init__()

    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        telegram_id: int | None = None

        if hasattr(event, "from_user") and event.from_user:
            telegram_id = event.from_user.id

        if telegram_id is not None:
            allowed = await check_spam(self.redis, telegram_id)
            if not allowed:
                await event.answer(self.LIMIT_MESSAGE)
                return  # stop processing

        return await handler(event, data)
