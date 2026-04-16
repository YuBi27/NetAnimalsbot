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
