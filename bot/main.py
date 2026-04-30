"""Точка входу бота — FastAPI webhook або long polling."""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, Awaitable, Callable

import redis.asyncio as aioredis
import uvicorn
from aiogram import BaseMiddleware, Bot, Dispatcher
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import TelegramObject, Update
from fastapi import FastAPI, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot.config import settings
from bot.handlers import admin, bite_report, broadcast, lost_browse, request, self_sterilization, user
from bot.middlewares.throttle import ThrottleMiddleware
from bot.models.models import create_tables

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Глобальні об'єкти (ініціалізуються при старті)
# ---------------------------------------------------------------------------

_bot: Bot | None = None
_dp: Dispatcher | None = None


class SessionMiddleware(BaseMiddleware):
    """Інжектує AsyncSession, Bot та Redis у кожен хендлер."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        bot: Bot,
        redis_client,
    ) -> None:
        self.session_factory = session_factory
        self._bot = bot
        self.redis = redis_client
        super().__init__()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with self.session_factory() as session:
            data["session"] = session
            data["bot_instance"] = self._bot
            data["redis"] = self.redis
            return await handler(event, data)


def _build_dispatcher(
    session_factory: async_sessionmaker[AsyncSession],
    bot: Bot,
    redis_client,
    storage: RedisStorage,
) -> Dispatcher:
    dp = Dispatcher(storage=storage)

    session_mw = SessionMiddleware(
        session_factory=session_factory,
        bot=bot,
        redis_client=redis_client,
    )
    dp.update.middleware(session_mw)
    request.router.message.middleware(ThrottleMiddleware(redis_client=redis_client))

    dp.include_router(user.router)
    dp.include_router(request.router)
    dp.include_router(self_sterilization.router)
    dp.include_router(lost_browse.router)
    dp.include_router(bite_report.router)
    dp.include_router(admin.router)
    dp.include_router(broadcast.router)

    return dp


# ---------------------------------------------------------------------------
# FastAPI lifespan — startup / shutdown
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _bot, _dp

    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    storage = RedisStorage(redis=redis_client)

    _bot = Bot(token=settings.BOT_TOKEN)
    _dp = _build_dispatcher(session_factory, _bot, redis_client, storage)

    await create_tables(engine)
    logger.info("Database tables initialised.")

    if settings.WEBHOOK_URL:
        webhook_url = f"{settings.WEBHOOK_URL.rstrip('/')}/webhook"
        await _bot.set_webhook(
            url=webhook_url,
            secret_token=settings.WEBHOOK_SECRET,
            drop_pending_updates=True,
        )
        logger.info("Webhook set: %s", webhook_url)
    else:
        # Long polling у фоновому завданні
        await _bot.delete_webhook(drop_pending_updates=True)
        asyncio.create_task(_dp.start_polling(_bot))
        logger.info("Long polling started.")

    yield

    # Shutdown
    if settings.WEBHOOK_URL:
        await _bot.delete_webhook()
    await _bot.session.close()
    await redis_client.aclose()
    await engine.dispose()
    logger.info("Bot stopped.")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="Volunteer Animal Bot", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    """Перевірка стану сервісу."""
    return {"status": "ok"}


@app.post("/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict:
    """Приймає оновлення від Telegram."""
    # Перевірка секретного токена
    if settings.WEBHOOK_SECRET and x_telegram_bot_api_secret_token != settings.WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Invalid secret token")

    if _bot is None or _dp is None:
        raise HTTPException(status_code=503, detail="Bot not initialised")

    body = await request.json()
    update = Update.model_validate(body)
    await _dp.feed_update(bot=_bot, update=update)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Точка входу
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run(
        "bot.main:app",
        host="0.0.0.0",
        port=settings.WEBHOOK_PORT,
        reload=False,
    )
