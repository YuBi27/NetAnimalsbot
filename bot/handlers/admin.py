"""Обробники адмін-команд."""

import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.keyboards.inline import (
    PAGE_SIZE,
    admin_requests_page_keyboard,
    export_format_keyboard,
)
from bot.models.models import ALLOWED_TRANSITIONS, Category, Request, Status, User
from bot.repositories.request_repo import get_request_by_id, get_requests_filtered
from bot.services.export_service import ExportService
from bot.services.request_service import RequestService
from bot.services.stats_service import StatsService
from bot.states import AdminCommentStates
from bot.utils.formatters import CATEGORY_LABELS, STATUS_LABELS
from bot.utils.maps import format_location

logger = logging.getLogger(__name__)

router = Router()

# Статуси що потребують коментаря
_COMMENT_REQUIRED = {Status.DONE, Status.REJECTED}

_STATUS_MAP: dict[str, Status] = {
    "in_progress": Status.IN_PROGRESS,
    "done": Status.DONE,
    "rejected": Status.REJECTED,
}

_STATUS_LABELS_MAP = {
    Status.IN_PROGRESS: "🔄 Взяти в роботу",
    Status.DONE: "✅ Закрити",
    Status.REJECTED: "❌ Відхилити",
}
_STATUS_KEYS_MAP = {
    Status.IN_PROGRESS: "in_progress",
    Status.DONE: "done",
    Status.REJECTED: "rejected",
}


def _is_admin(telegram_id: int) -> bool:
    return telegram_id == settings.ADMIN_ID


def _build_request_text(req: Request) -> str:
    cat = CATEGORY_LABELS.get(req.category, req.category)
    st = STATUS_LABELS.get(req.status, req.status)
    location = format_location(req.latitude, req.longitude, req.address_text)
    created = req.created_at.strftime("%d.%m.%Y %H:%M") if req.created_at else "—"
    contact = req.contact or "Не вказано"
    comment = f"\n<b>Коментар адміна:</b> {req.admin_comment}" if req.admin_comment else ""
    return (
        f"📋 <b>Заявка #{req.id}</b>\n\n"
        f"<b>Категорія:</b> {cat}\n"
        f"<b>Статус:</b> {st}\n"
        f"<b>Опис:</b> {req.description}\n"
        f"<b>Локація:</b> {location}\n"
        f"<b>Контакт:</b> {contact}\n"
        f"<b>Дата:</b> {created}"
        f"{comment}"
    )


def _build_status_keyboard(req: Request):
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    allowed = ALLOWED_TRANSITIONS.get(req.status, set())
    for st_enum in [Status.IN_PROGRESS, Status.DONE, Status.REJECTED]:
        if st_enum in allowed:
            builder.button(
                text=_STATUS_LABELS_MAP[st_enum],
                callback_data=f"status:{_STATUS_KEYS_MAP[st_enum]}:{req.id}",
            )
    builder.button(text="◀️ До списку", callback_data="admin_page:0")
    builder.adjust(1)
    return builder.as_markup()


async def _send_requests_page(target: Message | CallbackQuery, session: AsyncSession, page: int) -> None:
    all_requests = await get_requests_filtered(session)
    total = len(all_requests)

    if total == 0:
        text = "Заявок ще немає."
        kb = None
    else:
        start = page * PAGE_SIZE
        chunk = all_requests[start: start + PAGE_SIZE]
        text = f"📋 <b>Заявки ({total})</b> — сторінка {page + 1}/{(total + PAGE_SIZE - 1) // PAGE_SIZE}"
        kb = admin_requests_page_keyboard(chunk, page, total)

    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
        await target.answer()
    else:
        await target.answer(text, parse_mode="HTML", reply_markup=kb)


# ---------------------------------------------------------------------------
# Список заявок з пагінацією
# ---------------------------------------------------------------------------

@router.message(Command("requests"))
async def cmd_requests(message: Message, session: AsyncSession) -> None:
    if not message.from_user or not _is_admin(message.from_user.id):
        return
    await _send_requests_page(message, session, page=0)


@router.callback_query(F.data.startswith("admin_page:"))
async def admin_page_callback(callback: CallbackQuery, session: AsyncSession) -> None:
    if not callback.from_user or not _is_admin(callback.from_user.id):
        await callback.answer("Немає доступу.", show_alert=True)
        return
    page = int(callback.data.split(":")[1])
    await _send_requests_page(callback, session, page=page)


@router.callback_query(F.data == "noop")
async def noop_callback(callback: CallbackQuery) -> None:
    await callback.answer()


# ---------------------------------------------------------------------------
# Детальний перегляд заявки
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("admin_req:"))
async def admin_view_request(callback: CallbackQuery, session: AsyncSession) -> None:
    if not callback.from_user or not _is_admin(callback.from_user.id):
        await callback.answer("Немає доступу.", show_alert=True)
        return

    request_id = int(callback.data.split(":")[1])
    req = await get_request_by_id(session, request_id)
    if req is None:
        await callback.answer("Заявку не знайдено.", show_alert=True)
        return

    await callback.message.edit_text(
        _build_request_text(req),
        parse_mode="HTML",
        reply_markup=_build_status_keyboard(req),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Зміна статусу — з коментарем для DONE/REJECTED
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("status:"))
async def change_status_callback(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    bot_instance: Bot,
) -> None:
    if not callback.from_user or not _is_admin(callback.from_user.id):
        await callback.answer("Немає доступу.", show_alert=True)
        return

    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Некоректний формат.", show_alert=True)
        return

    _, status_key, request_id_str = parts
    new_status = _STATUS_MAP.get(status_key)
    if new_status is None:
        await callback.answer("Невідомий статус.", show_alert=True)
        return

    try:
        request_id = int(request_id_str)
    except ValueError:
        await callback.answer("Некоректний ID.", show_alert=True)
        return

    # Статуси DONE і REJECTED — показуємо inline-кнопки вибору коментаря
    if new_status in _COMMENT_REQUIRED:
        await state.set_state(AdminCommentStates.waiting_comment)
        await state.update_data(
            request_id=request_id,
            new_status=new_status.value,
        )
        action = "закриття" if new_status == Status.DONE else "відхилення"

        from aiogram.utils.keyboard import InlineKeyboardBuilder
        builder = InlineKeyboardBuilder()
        builder.button(text="⏭ Пропустити коментар", callback_data="admin_comment:skip")
        builder.button(text="✏️ Написати коментар", callback_data="admin_comment:write")
        builder.adjust(1)

        await callback.answer()
        await callback.message.answer(
            f"Заявка <b>#{request_id}</b> — <b>{action}</b>.\n\nДодати коментар для заявника?",
            parse_mode="HTML",
            reply_markup=builder.as_markup(),
        )
        return

    # IN_PROGRESS — без коментаря, одразу змінюємо
    service = RequestService(session=session, bot=bot_instance)
    try:
        req = await service.change_status(request_id, new_status, notify=True)
    except ValueError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    except Exception as exc:
        logger.error("Error changing status #%s: %s", request_id, exc)
        await callback.answer("Помилка при зміні статусу.", show_alert=True)
        return

    await callback.answer(f"✅ {STATUS_LABELS.get(new_status, new_status)}")
    try:
        await callback.message.edit_text(
            _build_request_text(req),
            parse_mode="HTML",
            reply_markup=_build_status_keyboard(req),
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Вибір коментаря через inline-кнопки
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "admin_comment:skip", AdminCommentStates.waiting_comment)
async def admin_comment_skip(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    bot_instance: Bot,
) -> None:
    """Пропустити коментар — одразу змінити статус."""
    await _apply_status_change(callback, state, session, bot_instance, comment=None)


@router.callback_query(F.data == "admin_comment:write", AdminCommentStates.waiting_comment)
async def admin_comment_write(callback: CallbackQuery) -> None:
    """Попросити ввести коментар текстом."""
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("✏️ Введіть коментар для заявника:")


# ---------------------------------------------------------------------------
# Отримання тексту коментаря
# ---------------------------------------------------------------------------

@router.message(AdminCommentStates.waiting_comment)
async def process_admin_comment(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    bot_instance: Bot,
) -> None:
    comment = message.text.strip() if message.text else None
    await _apply_status_change(message, state, session, bot_instance, comment=comment)


# ---------------------------------------------------------------------------
# Спільна логіка застосування зміни статусу
# ---------------------------------------------------------------------------

async def _apply_status_change(
    target: Message | CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    bot_instance: Bot,
    comment: str | None,
) -> None:
    fsm_data = await state.get_data()
    request_id: int = fsm_data["request_id"]
    new_status = Status(fsm_data["new_status"])
    await state.clear()

    req = await get_request_by_id(session, request_id)
    if req is None:
        msg = target if isinstance(target, Message) else target.message
        await msg.answer("Заявку не знайдено.")
        return

    req.admin_comment = comment
    await session.flush()

    service = RequestService(session=session, bot=bot_instance)
    try:
        req = await service.change_status(request_id, new_status, notify=False)
    except ValueError as exc:
        msg = target if isinstance(target, Message) else target.message
        await msg.answer(f"Помилка: {exc}")
        return

    # Сповіщення заявнику — статус + коментар одним повідомленням
    result = await session.execute(select(User).where(User.id == req.user_id))
    user = result.scalar_one_or_none()

    if user:
        st_label = STATUS_LABELS.get(new_status, new_status)
        user_text = f"ℹ️ Статус вашої заявки <b>#{req.id}</b> змінено: {st_label}"
        if comment:
            user_text += f"\n\n💬 <b>Коментар адміна:</b> {comment}"
        try:
            await bot_instance.send_message(
                chat_id=user.telegram_id,
                text=user_text,
                parse_mode="HTML",
            )
        except Exception as exc:
            logger.warning("Failed to notify user: %s", exc)

    st_label = STATUS_LABELS.get(new_status, new_status)
    confirm_text = f"✅ Заявку <b>#{req.id}</b> змінено на {st_label}."
    if comment:
        confirm_text += "\n💬 Коментар надіслано заявнику."

    msg = target if isinstance(target, Message) else target.message
    from bot.keyboards.reply import admin_menu_keyboard
    await msg.answer(confirm_text, parse_mode="HTML", reply_markup=admin_menu_keyboard())

    if isinstance(target, CallbackQuery):
        await target.answer()


# ---------------------------------------------------------------------------
# Статистика
# ---------------------------------------------------------------------------

@router.message(Command("stats"))
async def cmd_stats(message: Message, session: AsyncSession) -> None:
    if not message.from_user or not _is_admin(message.from_user.id):
        return
    stats = await StatsService(session).get_stats()
    cat_lines = "\n".join(f"  {CATEGORY_LABELS.get(c, c)}: {n}" for c, n in stats.by_category.items())
    st_lines = "\n".join(f"  {STATUS_LABELS.get(s, s)}: {n}" for s, n in stats.by_status.items())

    # Статистика укусів
    from sqlalchemy import func, select
    from bot.models.models import BiteReport
    bite_count_result = await session.execute(select(func.count()).select_from(BiteReport))
    bite_count = bite_count_result.scalar_one()

    text = (
        f"📊 <b>Статистика заявок</b>\n\n"
        f"<b>Всього:</b> {stats.total}\n\n"
        f"<b>За категоріями:</b>\n{cat_lines}\n\n"
        f"<b>За статусами:</b>\n{st_lines}\n\n"
        f"<b>Сьогодні:</b> {stats.today}\n"
        f"<b>Цього тижня:</b> {stats.week}\n"
        f"<b>Цього місяця:</b> {stats.month}\n\n"
        f"🚨 <b>Звіти про укуси:</b> {bite_count}"
    )
    await message.answer(text, parse_mode="HTML")


# ---------------------------------------------------------------------------
# Експорт
# ---------------------------------------------------------------------------

@router.message(Command("export"))
async def cmd_export(message: Message) -> None:
    if not message.from_user or not _is_admin(message.from_user.id):
        return
    await message.answer("Оберіть формат для експорту заявок:", reply_markup=export_format_keyboard())


@router.callback_query(F.data.in_({"export:csv", "export:xlsx"}))
async def export_callback(callback: CallbackQuery, session: AsyncSession) -> None:
    if not callback.from_user or not _is_admin(callback.from_user.id):
        await callback.answer("Немає доступу.", show_alert=True)
        return

    fmt = callback.data.split(":")[1]
    service = ExportService(session)
    await callback.answer("Генерую файл…")

    file_bytes = await service.export_csv() if fmt == "csv" else await service.export_xlsx()
    filename = f"requests.{fmt}"
    document = BufferedInputFile(file_bytes, filename=filename)
    from bot.keyboards.reply import admin_menu_keyboard
    await callback.message.answer_document(document, caption=f"Експорт заявок ({fmt.upper()})")
    await callback.message.answer("Головне меню:", reply_markup=admin_menu_keyboard())


# ===========================================================================
# Подача заявки адміністратором (AdminRequestStates)
# ===========================================================================

from bot.states import AdminRequestStates
from bot.utils.validators import validate_description, validate_media_count

_ADMIN_CATEGORY_MAP: dict[str, Category] = {
    "🐕 Загублена тварина": Category.LOST,
    "🩹 Поранена або хвора тварина": Category.INJURED,
    "✂️ Стерилізація": Category.STERILIZATION,
    "⚠️ Агресивна тварина": Category.AGGRESSIVE,
    "💀 Мертва тварина": Category.DEAD,
}

_ADMIN_MAX_MEDIA = 5


def _admin_category_keyboard():
    """Вибір категорії для адміна — inline-кнопки."""
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    for label, cat in _ADMIN_CATEGORY_MAP.items():
        builder.button(text=label, callback_data=f"adm_req_cat:{cat.value}")
    builder.button(text="❌ Скасувати", callback_data="adm_req_cancel")
    builder.adjust(1)
    return builder.as_markup()


def _admin_location_keyboard():
    from aiogram.types import KeyboardButton, ReplyKeyboardMarkup
    from aiogram.utils.keyboard import ReplyKeyboardBuilder
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="📍 Поділитися геолокацією", request_location=True))
    builder.row(KeyboardButton(text="Ввести адресу текстом"))
    builder.row(KeyboardButton(text="❌ Скасувати заявку"))
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)


def _admin_description_keyboard():
    from aiogram.types import KeyboardButton
    from aiogram.utils.keyboard import ReplyKeyboardBuilder
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="◀️ Назад"), KeyboardButton(text="❌ Скасувати заявку"))
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)


def _admin_media_keyboard(count: int):
    from aiogram.types import KeyboardButton
    from aiogram.utils.keyboard import ReplyKeyboardBuilder
    builder = ReplyKeyboardBuilder()
    if count > 0:
        builder.row(KeyboardButton(text="➡️ Далі"))
    builder.row(KeyboardButton(text="⏭ Пропустити медіа"))
    builder.row(KeyboardButton(text="◀️ Назад"), KeyboardButton(text="❌ Скасувати заявку"))
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)


def _admin_contact_keyboard():
    from aiogram.types import KeyboardButton
    from aiogram.utils.keyboard import ReplyKeyboardBuilder
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="📱 Поділитися контактом", request_contact=True))
    builder.row(KeyboardButton(text="Ввести @username"))
    builder.row(KeyboardButton(text="⏭ Пропустити контакт"))
    builder.row(KeyboardButton(text="◀️ Назад"), KeyboardButton(text="❌ Скасувати заявку"))
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)


# ---------------------------------------------------------------------------
# Крок 1: Вибір категорії (inline)
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("adm_req_cat:"), AdminRequestStates.waiting_category)
async def adm_req_choose_category(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Немає доступу.", show_alert=True)
        return

    cat_value = callback.data.split(":", 1)[1]
    try:
        category = Category(cat_value)
    except ValueError:
        await callback.answer("Невідома категорія.", show_alert=True)
        return

    await state.update_data(adm_category=cat_value, adm_media=[])
    await state.set_state(AdminRequestStates.waiting_location)

    from bot.utils.formatters import CATEGORY_LABELS
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        f"Обрано: <b>{CATEGORY_LABELS[category]}</b>\n\n"
        "📍 Надішліть геолокацію або введіть адресу текстом:",
        reply_markup=_admin_location_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Крок 2: Локація
# ---------------------------------------------------------------------------

@router.message(AdminRequestStates.waiting_location, F.location)
async def adm_req_location_geo(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    await state.update_data(
        adm_latitude=message.location.latitude,
        adm_longitude=message.location.longitude,
        adm_address_text=None,
    )
    await state.set_state(AdminRequestStates.waiting_description)
    await message.answer(
        "✅ Геолокацію отримано.\n\n📝 Опишіть ситуацію (мінімум 10 символів):",
        reply_markup=_admin_description_keyboard(),
    )


@router.message(
    AdminRequestStates.waiting_location,
    F.text & ~F.text.in_({"❌ Скасувати заявку"}),
)
async def adm_req_location_text(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    await state.update_data(adm_latitude=None, adm_longitude=None, adm_address_text=message.text.strip())
    await state.set_state(AdminRequestStates.waiting_description)
    await message.answer(
        "✅ Адресу збережено.\n\n📝 Опишіть ситуацію (мінімум 10 символів):",
        reply_markup=_admin_description_keyboard(),
    )


# ---------------------------------------------------------------------------
# Крок 3: Опис
# ---------------------------------------------------------------------------

@router.message(AdminRequestStates.waiting_description, F.text == "◀️ Назад")
async def adm_req_back_to_location(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    await state.set_state(AdminRequestStates.waiting_location)
    await message.answer(
        "📍 Надішліть геолокацію або введіть адресу текстом:",
        reply_markup=_admin_location_keyboard(),
    )


@router.message(
    AdminRequestStates.waiting_description,
    F.text & ~F.text.in_({"◀️ Назад", "❌ Скасувати заявку"}),
)
async def adm_req_description(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    text = message.text.strip()
    if not validate_description(text):
        await message.answer("⚠️ Опис занадто короткий. Введіть щонайменше 10 символів:")
        return
    await state.update_data(adm_description=text)
    await state.set_state(AdminRequestStates.waiting_media)
    fsm_data = await state.get_data()
    count = len(fsm_data.get("adm_media", []))
    await message.answer(
        "✅ Опис збережено.\n\n📷 Надішліть фото або відео (до 5 файлів), або пропустіть:",
        reply_markup=_admin_media_keyboard(count),
    )


# ---------------------------------------------------------------------------
# Крок 4: Медіа
# ---------------------------------------------------------------------------

@router.message(AdminRequestStates.waiting_media, F.text == "◀️ Назад")
async def adm_req_back_to_description(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    await state.set_state(AdminRequestStates.waiting_description)
    await message.answer(
        "📝 Введіть опис ситуації (мінімум 10 символів):",
        reply_markup=_admin_description_keyboard(),
    )


@router.message(AdminRequestStates.waiting_media, F.photo | F.video)
async def adm_req_media(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    fsm_data = await state.get_data()
    media: list[dict] = fsm_data.get("adm_media", [])

    if not validate_media_count(len(media)):
        await message.answer(f"⚠️ Досягнуто ліміт {_ADMIN_MAX_MEDIA} файлів. Натисніть «➡️ Далі».")
        return

    if message.photo:
        media.append({"file_id": message.photo[-1].file_id, "type": "photo"})
    else:
        media.append({"file_id": message.video.file_id, "type": "video"})

    await state.update_data(adm_media=media)
    remaining = _ADMIN_MAX_MEDIA - len(media)

    if remaining > 0:
        await message.answer(
            f"✅ Файл додано ({len(media)}/{_ADMIN_MAX_MEDIA}). Ще {remaining} або натисніть «➡️ Далі»:",
            reply_markup=_admin_media_keyboard(len(media)),
        )
    else:
        await state.set_state(AdminRequestStates.waiting_contact)
        await message.answer(
            f"✅ Додано {_ADMIN_MAX_MEDIA} файлів.\n\n📱 Вкажіть контакт або пропустіть:",
            reply_markup=_admin_contact_keyboard(),
        )


@router.message(AdminRequestStates.waiting_media, F.text.in_({"⏭ Пропустити медіа", "➡️ Далі"}))
async def adm_req_skip_media(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    await state.set_state(AdminRequestStates.waiting_contact)
    await message.answer(
        "📱 Вкажіть контакт або пропустіть:",
        reply_markup=_admin_contact_keyboard(),
    )


# ---------------------------------------------------------------------------
# Крок 5: Контакт
# ---------------------------------------------------------------------------

@router.message(AdminRequestStates.waiting_contact, F.text == "◀️ Назад")
async def adm_req_back_to_media(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    await state.set_state(AdminRequestStates.waiting_media)
    fsm_data = await state.get_data()
    count = len(fsm_data.get("adm_media", []))
    await message.answer(
        "📷 Надішліть фото або відео (до 5 файлів), або пропустіть:",
        reply_markup=_admin_media_keyboard(count),
    )


@router.message(AdminRequestStates.waiting_contact, F.contact)
async def adm_req_contact_shared(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    c = message.contact
    name = f"{c.first_name or ''} {c.last_name or ''}".strip()
    contact_str = f"{name} ({c.phone_number})" if name else c.phone_number
    await state.update_data(adm_contact=contact_str)
    await _adm_show_confirmation(message, state)


@router.message(
    AdminRequestStates.waiting_contact,
    F.text.in_({"⏭ Пропустити контакт"}),
)
async def adm_req_skip_contact(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    await state.update_data(adm_contact=None)
    await _adm_show_confirmation(message, state)


@router.message(
    AdminRequestStates.waiting_contact,
    F.text & ~F.text.in_({"◀️ Назад", "❌ Скасувати заявку", "⏭ Пропустити контакт"}),
)
async def adm_req_contact_text(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    await state.update_data(adm_contact=message.text.strip())
    await _adm_show_confirmation(message, state)


# ---------------------------------------------------------------------------
# Крок 6: Підтвердження
# ---------------------------------------------------------------------------

async def _adm_show_confirmation(message: Message, state: FSMContext) -> None:
    from aiogram.types import ReplyKeyboardRemove
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from bot.models.models import Category
    from bot.utils.formatters import CATEGORY_LABELS
    from bot.utils.maps import make_maps_link

    fsm_data = await state.get_data()
    await state.set_state(AdminRequestStates.confirming)

    category = Category(fsm_data["adm_category"])
    lat = fsm_data.get("adm_latitude")
    lon = fsm_data.get("adm_longitude")
    address_text = fsm_data.get("adm_address_text")
    contact = fsm_data.get("adm_contact") or "Не вказано"
    media_count = len(fsm_data.get("adm_media", []))

    if lat is not None and lon is not None:
        location_str = make_maps_link(lat, lon)
        if address_text:
            location_str += f"\n{address_text}"
    elif address_text:
        location_str = address_text
    else:
        location_str = "Не вказано"

    summary = (
        f"📋 <b>Перевірте заявку:</b>\n\n"
        f"<b>Категорія:</b> {CATEGORY_LABELS[category]}\n"
        f"<b>Опис:</b> {fsm_data.get('adm_description', '—')}\n"
        f"<b>Локація:</b> {location_str}\n"
        f"<b>Контакт:</b> {contact}\n"
        f"<b>Медіафайлів:</b> {media_count}"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Зберегти заявку", callback_data="adm_req:confirm")
    builder.button(text="◀️ Назад", callback_data="adm_req:back_from_confirm")
    builder.button(text="❌ Скасувати", callback_data="adm_req:cancel")
    builder.adjust(1)

    await message.answer("⏳", reply_markup=ReplyKeyboardRemove())
    await message.answer(summary, reply_markup=builder.as_markup(), parse_mode="HTML")


@router.callback_query(AdminRequestStates.confirming, F.data == "adm_req:back_from_confirm")
async def adm_req_back_from_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Немає доступу.", show_alert=True)
        return
    await state.set_state(AdminRequestStates.waiting_contact)
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.message.answer(
        "📱 Вкажіть контакт або пропустіть:",
        reply_markup=_admin_contact_keyboard(),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Скасування на будь-якому кроці
# ---------------------------------------------------------------------------

@router.message(
    F.text == "❌ Скасувати заявку",
    F.func(lambda m: True),  # буде відловлено лише у відповідних станах завдяки фільтрам нижче
    AdminRequestStates.waiting_location,
)
async def adm_req_cancel_location(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    await state.clear()
    from bot.keyboards.reply import admin_menu_keyboard
    await message.answer("❌ Заявку скасовано.", reply_markup=admin_menu_keyboard())


@router.message(F.text == "❌ Скасувати заявку", AdminRequestStates.waiting_description)
async def adm_req_cancel_description(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    await state.clear()
    from bot.keyboards.reply import admin_menu_keyboard
    await message.answer("❌ Заявку скасовано.", reply_markup=admin_menu_keyboard())


@router.message(F.text == "❌ Скасувати заявку", AdminRequestStates.waiting_media)
async def adm_req_cancel_media(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    await state.clear()
    from bot.keyboards.reply import admin_menu_keyboard
    await message.answer("❌ Заявку скасовано.", reply_markup=admin_menu_keyboard())


@router.message(F.text == "❌ Скасувати заявку", AdminRequestStates.waiting_contact)
async def adm_req_cancel_contact(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    await state.clear()
    from bot.keyboards.reply import admin_menu_keyboard
    await message.answer("❌ Заявку скасовано.", reply_markup=admin_menu_keyboard())


@router.callback_query(F.data == "adm_req:cancel")
async def adm_req_cancel_callback(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Немає доступу.", show_alert=True)
        return
    await state.clear()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    from bot.keyboards.reply import admin_menu_keyboard
    await callback.message.answer("❌ Заявку скасовано.", reply_markup=admin_menu_keyboard())
    await callback.answer()


# ---------------------------------------------------------------------------
# Підтвердження та збереження
# ---------------------------------------------------------------------------

@router.callback_query(AdminRequestStates.confirming, F.data == "adm_req:confirm")
async def adm_req_confirm(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    bot_instance: Bot,
) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Немає доступу.", show_alert=True)
        return

    fsm_data = await state.get_data()

    # Знаходимо або створюємо запис адміна у таблиці users
    from bot.repositories.user_repo import get_or_create_user
    user = await get_or_create_user(
        session=session,
        telegram_id=callback.from_user.id,
        username=callback.from_user.username,
    )

    category = Category(fsm_data["adm_category"])
    lat = fsm_data.get("adm_latitude")
    lon = fsm_data.get("adm_longitude")
    address_text = fsm_data.get("adm_address_text")
    media_files: list[dict] = fsm_data.get("adm_media", [])
    contact = fsm_data.get("adm_contact")

    location: dict | None = None
    if lat is not None and lon is not None:
        location = {"latitude": lat, "longitude": lon}
        if address_text:
            location["address_text"] = address_text
    elif address_text:
        location = {"address_text": address_text}

    service = RequestService(session=session, bot=bot_instance)
    req = await service.create_request(
        user_id=user.id,
        category=category,
        description=fsm_data.get("adm_description", ""),
        location=location,
        media_files=media_files,
        contact=contact,
    )

    # Публікуємо в канал (INJURED/LOST), але НЕ надсилаємо сповіщення адміну
    try:
        await service.publish_to_channel(req, settings.CHANNEL_ID)
    except Exception as exc:
        logger.warning("Failed to publish admin request to channel: %s", exc)

    await state.clear()

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    from bot.keyboards.reply import admin_menu_keyboard
    await callback.message.answer(
        f"✅ Заявку <b>#{req.id}</b> успішно створено і додано до загальної бази.",
        reply_markup=admin_menu_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()
