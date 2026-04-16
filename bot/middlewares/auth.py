"""
Auth middleware — перевірка прав адміністратора.

Перевіряє telegram_id відправника проти налаштованого ADMIN_ID.
Неавторизовані запити відхиляються без розкриття деталей.
"""

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message


def is_admin(telegram_id: int, admin_id: int) -> bool:
    """Returns True if telegram_id matches admin_id."""
    return telegram_id == admin_id


class AdminAuthMiddleware(BaseMiddleware):
    """
    aiogram 3.x middleware that restricts access to admin handlers.

    If the sender's telegram_id does not match admin_id,
    sends "Немає доступу" and stops further processing.
    """

    DENY_MESSAGE = "Немає доступу"

    def __init__(self, admin_id: int) -> None:
        self.admin_id = admin_id
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

        if telegram_id is None or not is_admin(telegram_id, self.admin_id):
            if hasattr(event, "answer"):
                await event.answer(self.DENY_MESSAGE)
            return  # stop processing

        return await handler(event, data)
