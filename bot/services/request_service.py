"""Сервіс бізнес-логіки для заявок (Вимоги 3.1–3.5, 4.1–4.5, 5.1–5.3)."""

import logging
from typing import Any

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.models import Category, MediaType, Request, Status, User
from bot.repositories import media_repo, request_repo, user_repo
from bot.utils.formatters import format_channel_post, format_status_notification

logger = logging.getLogger(__name__)

# Categories that get auto-published to the channel (Req 3.5)
_PUBLISHABLE_CATEGORIES = {Category.INJURED, Category.LOST}


class RequestService:
    """Orchestrates request creation, status changes, notifications and channel publishing."""

    def __init__(self, session: AsyncSession, bot: Bot) -> None:
        self.session = session
        self.bot = bot

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def create_request(
        self,
        user_id: int,
        category: Category,
        description: str,
        location: dict[str, Any] | None,
        media_files: list[dict[str, str]] | None,
        contact: str | None,
    ) -> Request:
        """Persist a new request, attach media, and trigger notifications.

        media_files: list of {"file_id": str, "type": "photo"|"video"}
        location:    {"latitude": float, "longitude": float} or {"address_text": str}

        Req 3.1 — saves with status NEW and unique ID
        Req 3.3 — (admin notification is handled by the handler layer)
        Req 3.5 — publishes to channel for INJURED/LOST
        """
        req = await request_repo.create_request(
            self.session,
            user_id=user_id,
            category=category,
            description=description,
            location=location,
            contact=contact,
        )

        # Attach media files (Req 2.7, 2.8 — limit enforced in media_repo)
        for mf in (media_files or []):
            media_type = MediaType(mf["type"])
            await media_repo.add_media(self.session, req.id, mf["file_id"], media_type)

        await self.session.commit()

        # Reload with eager-loaded media to avoid lazy-load issues
        req = await self._load_request(req.id)
        return req

    async def change_status(self, request_id: int, new_status: Status, notify: bool = True) -> Request:
        """Validate transition, persist new status, and optionally notify the request owner."""
        req = await request_repo.update_status(self.session, request_id, new_status)
        await self.session.commit()

        req = await self._load_request(req.id)

        if notify:
            user_result = await self.session.execute(
                select(User).where(User.id == req.user_id)
            )
            user = user_result.scalar_one_or_none()
            if user is not None:
                await self.notify_user_status_change(req, user.telegram_id)

        return req

    async def get_user_requests(self, telegram_id: int) -> list[Request]:
        """Return all requests for a user identified by their Telegram ID.

        Req 5.1–5.3
        """
        result = await self.session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            return []
        return await request_repo.get_user_requests(self.session, user.id)

    async def publish_to_channel(self, request: Request, channel_id: str) -> None:
        """Publish request to the Telegram channel (only INJURED and LOST).

        Req 3.5
        """
        if request.category not in _PUBLISHABLE_CATEGORIES:
            return

        text = format_channel_post(request)

        # Load media explicitly to avoid lazy-load issues
        media_list = await media_repo.get_media_by_request(self.session, request.id)
        photos = [m for m in media_list if m.type == MediaType.PHOTO]
        if photos:
            await self.bot.send_photo(
                chat_id=channel_id,
                photo=photos[0].file_id,
                caption=text,
                parse_mode="HTML",
            )
            return

        await self.bot.send_message(chat_id=channel_id, text=text, parse_mode="HTML")

    async def notify_user_status_change(
        self, request: Request, user_telegram_id: int
    ) -> None:
        """Send a status-change notification to the request owner.

        Req 4.4
        """
        text = format_status_notification(request)
        try:
            await self.bot.send_message(
                chat_id=user_telegram_id, text=text, parse_mode="HTML"
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to notify user %s about request #%s: %s",
                user_telegram_id,
                request.id,
                exc,
            )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _load_request(self, request_id: int) -> Request:
        """Load a Request with its media eagerly to avoid lazy-load issues."""
        result = await self.session.execute(
            select(Request)
            .options(selectinload(Request.media))
            .where(Request.id == request_id)
        )
        return result.scalar_one()
