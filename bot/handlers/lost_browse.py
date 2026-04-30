"""Перегляд загублених тварин з фото та можливістю повідомити про знахідку."""

import logging

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.keyboards.reply import main_menu_keyboard, smart_menu_keyboard
from bot.models.models import Category, MediaType, Request, Status, User
from bot.repositories.request_repo import get_requests_filtered
from bot.utils.formatters import format_location
from bot.utils.maps import make_maps_link

logger = logging.getLogger(__name__)
router = Router()


def _lost_card_keyboard(request_id: int) -> object:
    builder = InlineKeyboardBuilder()
    builder.button(text="🙋 Я знайшов цю тварину!", callback_data=f"found:{request_id}")
    return builder.as_markup()


def _format_lost_card(req: Request, index: int, total: int) -> str:
    location = format_location(req.latitude, req.longitude, req.address_text)
    created = req.created_at.strftime("%d.%m.%Y") if req.created_at else "—"
    return (
        f"🐾 <b>Загублена тварина #{req.id}</b> ({index}/{total})\n\n"
        f"<b>Опис:</b> {req.description}\n"
        f"<b>Місце:</b> {location}\n"
        f"<b>Дата заявки:</b> {created}"
    )


@router.message(F.text == "🗺️ Переглянути загублених тварин")
async def browse_lost_animals(message: Message, session: AsyncSession, state: FSMContext) -> None:
    """Показує список активних заявок про загублених тварин."""
    from bot.models.models import Request as RequestModel
    result_new = await session.execute(
        select(RequestModel)
        .options(selectinload(RequestModel.media))
        .where(RequestModel.category == Category.LOST)
        .where(RequestModel.status.in_([Status.NEW, Status.IN_PROGRESS]))
        .order_by(RequestModel.created_at.desc())
    )
    all_lost = result_new.scalars().all()

    if not all_lost:
        sent = await message.answer(
            "🐾 Наразі немає активних заявок про загублених тварин.",
            reply_markup=smart_menu_keyboard(message.from_user.id),
        )
        return

    sent = await message.answer(
        f"🔍 <b>Загублені тварини</b> — знайдено {len(all_lost)} активних заявок.\n\n"
        f"Перегляньте їх нижче. Якщо впізнали тварину — натисніть кнопку під фото.",
        parse_mode="HTML",
    )

    for i, req in enumerate(all_lost, 1):
        text = _format_lost_card(req, i, len(all_lost))
        kb = _lost_card_keyboard(req.id)
        photo_media = next((m for m in req.media if m.type == MediaType.PHOTO), None)
        try:
            if photo_media:
                sent = await message.answer_photo(
                    photo=photo_media.file_id,
                    caption=text,
                    parse_mode="HTML",
                    reply_markup=kb,
                )
            else:
                sent = await message.answer(text, parse_mode="HTML", reply_markup=kb)
        except Exception as exc:
            logger.warning("Failed to send lost animal card #%s: %s", req.id, exc)

    sent = await message.answer("Це всі активні заявки.", reply_markup=smart_menu_keyboard(message.from_user.id))


def _format_sterilized_card(req: Request, index: int, total: int) -> str:
    location = format_location(req.latitude, req.longitude, req.address_text)
    created = req.created_at.strftime("%d.%m.%Y") if req.created_at else "—"
    comment = f"\n💬 <b>Коментар:</b> {req.admin_comment}" if req.admin_comment else ""
    return (
        f"✂️ <b>Стерилізована тварина #{req.id}</b> ({index}/{total})\n\n"
        f"<b>Опис:</b> {req.description}\n"
        f"<b>Місце:</b> {location}\n"
        f"<b>Дата:</b> {created}"
        f"{comment}"
    )


@router.message(F.text == "🏷️ Стерилізовані тварини")
async def browse_sterilized_animals(message: Message, session: AsyncSession, state: FSMContext) -> None:
    """Показує список тварин що пройшли стерилізацію (статус DONE) — тільки для адміна."""
    from bot.keyboards.reply import admin_menu_keyboard

    if message.from_user.id not in settings.all_admin_ids:
        await message.answer("⛔️ Цей розділ доступний лише адміністратору.")
        return


    from bot.models.models import Request as RequestModel
    result = await session.execute(
        select(RequestModel)
        .options(selectinload(RequestModel.media))
        .where(RequestModel.category == Category.STERILIZATION)
        .where(RequestModel.status == Status.DONE)
        .order_by(RequestModel.created_at.desc())
    )
    all_sterilized = result.scalars().all()

    if not all_sterilized:
        sent = await message.answer(
            "✂️ Наразі немає записів про стерилізованих тварин.",
            reply_markup=admin_menu_keyboard(),
        )
        return

    sent = await message.answer(
        f"✂️ <b>Стерилізовані тварини</b> — знайдено {len(all_sterilized)} записів.\n\n"
        f"Перегляньте їх нижче.",
        parse_mode="HTML",
    )

    for i, req in enumerate(all_sterilized, 1):
        text = _format_sterilized_card(req, i, len(all_sterilized))
        photo_media = next((m for m in req.media if m.type == MediaType.PHOTO), None)
        try:
            if photo_media:
                sent = await message.answer_photo(
                    photo=photo_media.file_id,
                    caption=text,
                    parse_mode="HTML",
                )
            else:
                sent = await message.answer(text, parse_mode="HTML")
        except Exception as exc:
            logger.warning("Failed to send sterilized animal card #%s: %s", req.id, exc)

    sent = await message.answer("Це всі записи про стерилізованих тварин.", reply_markup=admin_menu_keyboard())


@router.callback_query(F.data.startswith("found:"))
async def report_found_animal(
    callback: CallbackQuery,
    session: AsyncSession,
    bot_instance: Bot,
) -> None:
    """Користувач повідомляє що знайшов тварину — надсилає контакт адміну."""
    request_id = int(callback.data.split(":")[1])

    # Отримуємо заявку
    from bot.repositories.request_repo import get_request_by_id
    req = await get_request_by_id(session, request_id)
    if req is None:
        await callback.answer("Заявку не знайдено.", show_alert=True)
        return

    # Отримуємо дані того хто знайшов
    finder = callback.from_user
    finder_info = f"@{finder.username}" if finder.username else f"ID: {finder.id}"
    finder_name = f"{finder.first_name or ''} {finder.last_name or ''}".strip() or "Невідомо"

    # Повідомляємо адміна
    admin_text = (
        f"🙋 <b>Знайдена тварина!</b>\n\n"
        f"<b>Заявка:</b> #{request_id}\n"
        f"<b>Опис тварини:</b> {req.description}\n\n"
        f"<b>Хто знайшов:</b> {finder_name}\n"
        f"<b>Контакт:</b> {finder_info}\n"
        f"<b>Telegram ID:</b> {finder.id}"
    )

    for admin_id in settings.all_admin_ids:
        try:
            await bot_instance.send_message(
                chat_id=admin_id,
                text=admin_text,
                parse_mode="HTML",
            )
        except Exception as exc:
            logger.error("Failed to notify admin %s about found animal: %s", admin_id, exc)

    await callback.answer("✅ Дякуємо! Адміністратор отримав ваше повідомлення.", show_alert=True)
    await callback.message.answer(
        "✅ <b>Дякуємо за повідомлення!</b>\n\n"
        "Адміністратор зв'яжеться з вами найближчим часом для уточнення деталей.",
        parse_mode="HTML",
        reply_markup=smart_menu_keyboard(message.from_user.id),
    )
