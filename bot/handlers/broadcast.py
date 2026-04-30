"""FSM-обробник масової розсилки."""

import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, KeyboardButton, Message, ReplyKeyboardMarkup, ReplyKeyboardRemove
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.services.broadcast_service import BroadcastService
from bot.states import BroadcastStates

logger = logging.getLogger(__name__)

router = Router()


def _is_admin(telegram_id: int) -> bool:
    return telegram_id in settings.all_admin_ids


def _cancel_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="❌ Скасувати"))
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)


def _skip_media_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="⏭ Пропустити медіа"))
    builder.row(KeyboardButton(text="❌ Скасувати"))
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)


def _confirm_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Надіслати", callback_data="broadcast:confirm")
    builder.button(text="❌ Скасувати", callback_data="broadcast:cancel")
    builder.adjust(2)
    return builder.as_markup()


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, state: FSMContext) -> None:
    if not message.from_user or not _is_admin(message.from_user.id):
        return
    await state.set_state(BroadcastStates.waiting_text)
    await message.answer(
        "📢 <b>Нова розсилка</b>\n\nВведіть текст повідомлення:",
        parse_mode="HTML",
        reply_markup=_cancel_keyboard(),
    )


@router.message(F.text == "❌ Скасувати", BroadcastStates())
async def cancel_broadcast(message: Message, state: FSMContext) -> None:
    await state.clear()
    from bot.keyboards.reply import admin_menu_keyboard
    await message.answer("Розсилку скасовано.", reply_markup=admin_menu_keyboard())


@router.message(BroadcastStates.waiting_text, F.text)
async def process_broadcast_text(message: Message, state: FSMContext) -> None:
    await state.update_data(broadcast_text=message.text)
    await state.set_state(BroadcastStates.waiting_media)
    await message.answer("Надішліть фото або відео (необов'язково):", reply_markup=_skip_media_keyboard())


@router.message(BroadcastStates.waiting_text)
async def process_broadcast_text_invalid(message: Message) -> None:
    await message.answer("Будь ласка, введіть текст повідомлення.")


@router.message(BroadcastStates.waiting_media, F.photo)
async def process_broadcast_media_photo(message: Message, state: FSMContext) -> None:
    await state.update_data(broadcast_media={"file_id": message.photo[-1].file_id, "type": "photo"})
    await _show_confirmation(message, state)


@router.message(BroadcastStates.waiting_media, F.video)
async def process_broadcast_media_video(message: Message, state: FSMContext) -> None:
    await state.update_data(broadcast_media={"file_id": message.video.file_id, "type": "video"})
    await _show_confirmation(message, state)


@router.message(BroadcastStates.waiting_media, F.text == "⏭ Пропустити медіа")
async def skip_broadcast_media(message: Message, state: FSMContext) -> None:
    await state.update_data(broadcast_media=None)
    await _show_confirmation(message, state)


@router.message(BroadcastStates.waiting_media)
async def process_broadcast_media_invalid(message: Message) -> None:
    await message.answer("Надішліть фото, відео або натисніть «⏭ Пропустити медіа».")


async def _show_confirmation(message: Message, state: FSMContext) -> None:
    fsm_data = await state.get_data()
    text = fsm_data.get("broadcast_text", "")
    media = fsm_data.get("broadcast_media")
    media_info = "немає"
    if media:
        media_info = "📷 фото" if media["type"] == "photo" else "🎥 відео"

    preview = (
        f"📢 <b>Підтвердження розсилки</b>\n\n"
        f"<b>Текст:</b>\n{text}\n\n"
        f"<b>Медіа:</b> {media_info}\n\n"
        f"Надіслати повідомлення всім користувачам?"
    )
    await state.set_state(BroadcastStates.confirming)
    await message.answer(preview, parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
    await message.answer("Оберіть дію:", reply_markup=_confirm_keyboard())


@router.callback_query(F.data == "broadcast:confirm", BroadcastStates.confirming)
async def confirm_broadcast(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    bot_instance: Bot,
) -> None:
    if not callback.from_user or not _is_admin(callback.from_user.id):
        await callback.answer("Немає доступу.", show_alert=True)
        return

    fsm_data = await state.get_data()
    text = fsm_data.get("broadcast_text", "")
    media = fsm_data.get("broadcast_media")

    await state.clear()
    await callback.answer("Розсилка розпочата…")
    await callback.message.edit_reply_markup(reply_markup=None)

    # Формуємо inline-кнопку "Написати адміну" якщо є ADMIN_USERNAME
    from bot.config import settings as cfg
    contact_markup = None
    if cfg.ADMIN_USERNAME:
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        builder = InlineKeyboardBuilder()
        username = cfg.ADMIN_USERNAME.lstrip("@")
        builder.button(text="✉️ Написати адміну", url=f"https://t.me/{username}")
        contact_markup = builder.as_markup()

    service = BroadcastService(session=session, bot=bot_instance)
    result = await service.send_broadcast(text=text, media=media, reply_markup=contact_markup)

    report = (
        f"✅ <b>Розсилку завершено</b>\n\n"
        f"Успішно: {result.success_count}\n"
        f"Помилок: {result.fail_count}"
    )
    from bot.keyboards.reply import admin_menu_keyboard
    await callback.message.answer(report, parse_mode="HTML", reply_markup=admin_menu_keyboard())


@router.callback_query(F.data == "broadcast:cancel", BroadcastStates.confirming)
async def cancel_broadcast_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer("Розсилку скасовано.")
    await callback.message.edit_reply_markup(reply_markup=None)
    from bot.keyboards.reply import admin_menu_keyboard
    await callback.message.answer("Розсилку скасовано.", reply_markup=admin_menu_keyboard())
