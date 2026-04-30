"""Утиліта для очищення чату — видаляє попередні повідомлення бота при переході між розділами."""

import logging
from aiogram import Bot
from aiogram.fsm.context import FSMContext

logger = logging.getLogger(__name__)

_FSM_KEY = "bot_msg_ids"


async def track_message(state: FSMContext, message_id: int) -> None:
    """Зберігає message_id повідомлення бота у FSM для подальшого видалення."""
    data = await state.get_data()
    ids: list[int] = data.get(_FSM_KEY, [])
    ids.append(message_id)
    # Зберігаємо не більше 50 останніх повідомлень
    if len(ids) > 50:
        ids = ids[-50:]
    await state.update_data({_FSM_KEY: ids})


async def clear_chat(
    bot: Bot,
    chat_id: int,
    state: FSMContext,
    keep_ids: list[int] | None = None,
) -> None:
    """Видаляє всі збережені повідомлення бота з чату.

    keep_ids — список message_id які НЕ треба видаляти (наприклад поточне).
    """
    data = await state.get_data()
    ids: list[int] = data.get(_FSM_KEY, [])
    keep = set(keep_ids or [])

    deleted = 0
    for mid in ids:
        if mid in keep:
            continue
        try:
            await bot.delete_message(chat_id=chat_id, message_id=mid)
            deleted += 1
        except Exception:
            pass  # Повідомлення вже видалено або старіше 48 годин

    # Очищаємо список, залишаємо тільки keep_ids
    await state.update_data({_FSM_KEY: list(keep)})
    if deleted:
        logger.debug("Cleared %d messages in chat %d", deleted, chat_id)
