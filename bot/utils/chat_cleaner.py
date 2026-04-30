"""Утиліта для очищення чату — видаляє попередні повідомлення бота при переході між розділами."""

import logging
from aiogram import Bot
from aiogram.fsm.context import FSMContext

logger = logging.getLogger(__name__)

_FSM_KEY = "bot_msg_ids"


async def track_message(state: FSMContext, message_id: int, has_keyboard: bool = False) -> None:
    """Зберігає message_id повідомлення бота у FSM для подальшого видалення."""
    data = await state.get_data()
    ids: list[int] = data.get(_FSM_KEY, [])
    ids.append(message_id)
    if len(ids) > 50:
        ids = ids[-50:]
    await state.update_data({_FSM_KEY: ids})


async def clear_chat(bot: Bot, chat_id: int, state: FSMContext) -> None:
    """Видаляє всі збережені повідомлення бота з чату.

    ВАЖЛИВО: після виклику цієї функції ОБОВ'ЯЗКОВО надсилайте нове
    повідомлення з reply_markup — інакше клавіатура зникне.
    """
    data = await state.get_data()
    ids: list[int] = data.get(_FSM_KEY, [])

    deleted = 0
    for mid in ids:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=mid)
            deleted += 1
        except Exception:
            pass  # Вже видалено або старіше 48 годин

    await state.update_data({_FSM_KEY: []})
    if deleted:
        logger.debug("Cleared %d messages in chat %d", deleted, chat_id)
