"""Сервіс масової розсилки (Вимоги 7.2, 7.3, 7.4)."""

import asyncio
import logging
from dataclasses import dataclass

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from bot.repositories import user_repo

logger = logging.getLogger(__name__)

# Throttle delay between sends — Req 7.2 (≥ 50 ms)
_THROTTLE_DELAY = 0.05


@dataclass
class BroadcastResult:
    success_count: int
    fail_count: int


class BroadcastService:
    """Sends a broadcast message to all users with throttling and error logging."""

    def __init__(self, session: AsyncSession, bot: Bot) -> None:
        self.session = session
        self.bot = bot

    async def send_broadcast(
        self,
        text: str,
        media: dict | None = None,
        reply_markup=None,
    ) -> BroadcastResult:
        """Send *text* (with optional *media*) to every user in the database.

        media: None  or  {"file_id": str, "type": "photo" | "video"}

        Throttle: asyncio.sleep(0.05) between each send (Req 7.2).
        Logs success/failure per user (Req 7.3, 7.4).
        Returns BroadcastResult with success_count and fail_count.
        """
        users = await user_repo.get_all_users(self.session)

        success_count = 0
        fail_count = 0

        for user in users:
            try:
                await self._send_to_user(user.telegram_id, text, media, reply_markup)
                logger.info("Broadcast sent to user %s", user.telegram_id)
                success_count += 1
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Broadcast failed for user %s: %s", user.telegram_id, exc
                )
                fail_count += 1

            # Throttle — Req 7.2
            await asyncio.sleep(_THROTTLE_DELAY)

        logger.info(
            "Broadcast complete: %d success, %d failed", success_count, fail_count
        )
        return BroadcastResult(success_count=success_count, fail_count=fail_count)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _send_to_user(
        self,
        chat_id: int,
        text: str,
        media: dict | None,
        reply_markup=None,
    ) -> None:
        """Dispatch a single message (text or media) to one user."""
        if media is None:
            await self.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
            return

        media_type = media.get("type")
        file_id = media["file_id"]

        if media_type == "photo":
            await self.bot.send_photo(chat_id=chat_id, photo=file_id, caption=text, reply_markup=reply_markup)
        elif media_type == "video":
            await self.bot.send_video(chat_id=chat_id, video=file_id, caption=text, reply_markup=reply_markup)
        else:
            await self.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
