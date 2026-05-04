"""Обробники для користувацьких команд та меню."""

import logging

from aiogram import Bot, F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.keyboards.inline import user_requests_keyboard
from bot.keyboards.reply import admin_menu_keyboard, admin_request_submit_keyboard, main_menu_keyboard, main_menu_with_draft_keyboard, smart_menu_keyboard
from bot.repositories.request_repo import get_request_by_id, get_user_requests
from bot.repositories.user_repo import get_or_create_user
from bot.utils.formatters import CATEGORY_LABELS, STATUS_LABELS
from bot.utils.maps import format_location

logger = logging.getLogger(__name__)
router = Router()

INFO_TEXT = (
    "📖 <b>Нетішин Animals Bot — довідка</b>\n\n"
    "Цей бот допомагає волонтерам міста Нетішин збирати та обробляти заявки про тварин, "
    "які потребують допомоги.\n\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "🐾 <b>Як подати заявку?</b>\n\n"
    "1️⃣ Оберіть категорію у головному меню:\n"
    "   • 🐾 <b>Загублена тварина</b> — знайшли або загубили тварину\n"
    "   • 🚑 <b>Поранена тварина</b> — тварина потребує медичної допомоги\n"
    "   • 💉 <b>Стерилізація</b> — запит на стерилізацію безпритульної тварини\n"
    "   • 🪦 <b>Мертва тварина</b> — виявлено загиблу тварину на вулиці\n"
    "   • 🔬 <b>Стерилізую самостійно</b> — самостійна стерилізація з погодженням\n\n"
    "2️⃣ <b>Вкажіть місце</b> — поділіться геолокацією або введіть адресу текстом\n\n"
    "3️⃣ <b>Опишіть ситуацію</b> — мінімум 10 символів. Чим детальніше — тим краще:\n"
    "   порода, колір, особливі прикмети, стан тварини\n\n"
    "4️⃣ <b>Додайте фото або відео</b> — до 5 файлів (необов'язково, але дуже бажано)\n\n"
    "5️⃣ <b>Вкажіть контакт</b> — поділіться номером телефону або введіть @username\n\n"
    "6️⃣ <b>Перевірте та відправте</b> заявку\n\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "🗂️ <b>Мої заявки</b>\n\n"
    "Тут ви можете переглянути всі свої заявки та їх поточний статус:\n"
    "   • 🆕 <b>Нова</b> — заявку отримано, очікує розгляду\n"
    "   • 🔄 <b>В роботі</b> — волонтер вже займається вашою заявкою\n"
    "   • ⏳ <b>Очікує фідбек</b> — стерилізацію погоджено, чекаємо вашого звіту\n"
    "   • ✅ <b>Виконано</b> — питання вирішено\n"
    "   • ❌ <b>Відхилено</b> — заявку відхилено (причина буде вказана)\n\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "🔔 <b>Сповіщення</b>\n\n"
    "Коли статус вашої заявки зміниться — ви отримаєте повідомлення від бота "
    "з новим статусом та коментарем від волонтера.\n\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "💡 <b>Корисні поради</b>\n\n"
    "• Фото значно прискорює обробку заявки\n"
    "• Вказуйте точну адресу або геолокацію\n"
    "• Можна подати не більше 3 заявок на годину\n"
    "• Кнопка ◀️ <b>Назад</b> дозволяє виправити попередній крок\n"
    "• Кнопка ❌ <b>Скасувати</b> скасовує заявку на будь-якому кроці\n\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "📞 <b>Контакти</b>\n\n"
    "З питань роботи бота звертайтесь до адміністратора."
)


def _is_admin(telegram_id: int) -> bool:
    return telegram_id in settings.all_admin_ids


@router.message(CommandStart())
async def cmd_start(message: Message, session: AsyncSession, state: FSMContext) -> None:
    await get_or_create_user(
        session=session,
        telegram_id=message.from_user.id,
        username=message.from_user.username,
    )
    await session.commit()

    # Очищаємо попередній чат

    name = message.from_user.first_name or "друже"

    if _is_admin(message.from_user.id):
        sent = await message.answer(
            f"Привіт, {name}! 👋 Ви увійшли як <b>адміністратор</b>.\n\nОберіть дію у меню нижче:",
            reply_markup=admin_menu_keyboard(),
            parse_mode="HTML",
        )
        return

    fsm_data = await state.get_data()
    has_draft = fsm_data.get("_is_draft") and fsm_data.get("category")

    if has_draft:
        sent = await message.answer(
            f"Привіт, {name}! 👋\n\nУ вас є незавершена заявка. Оберіть дію:",
            reply_markup=main_menu_with_draft_keyboard(),
        )
    else:
        sent = await message.answer(
            f"Привіт, {name}! 👋\n\nЯ бот для волонтерів — допомагаю збирати заявки про тварин.\nОберіть дію у меню нижче:",
            reply_markup=smart_menu_keyboard(message.from_user.id),
        )


# ---------------------------------------------------------------------------
# Адмін-кнопки меню
# ---------------------------------------------------------------------------

@router.message(F.text == "📝 Подати заявку")
async def admin_btn_submit_request(message: Message) -> None:
    """Адмін переходить у режим подачі заявки."""
    if not _is_admin(message.from_user.id):
        return
    await message.answer(
        "📝 Оберіть категорію заявки:",
        reply_markup=admin_request_submit_keyboard(),
    )


@router.message(F.text == "📑 Всі заявки")
async def admin_btn_requests(message: Message, session: AsyncSession, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    from bot.handlers.admin import _send_requests_page
    await _send_requests_page(message, session, page=0, state=state)


@router.message(F.text == "📈 Статистика")
async def admin_btn_stats(message: Message, session: AsyncSession, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    from bot.services.stats_service import StatsService
    stats = await StatsService(session).get_stats()

    cat_lines = "\n".join(
        f"  {CATEGORY_LABELS.get(cat, cat)}: {count}"
        for cat, count in stats.by_category.items()
    )
    st_lines = "\n".join(
        f"  {STATUS_LABELS.get(st, st)}: {count}"
        for st, count in stats.by_status.items()
    )
    text = (
        f"📊 <b>Статистика заявок</b>\n\n"
        f"<b>Всього:</b> {stats.total}\n\n"
        f"<b>За категоріями:</b>\n{cat_lines}\n\n"
        f"<b>За статусами:</b>\n{st_lines}\n\n"
        f"<b>Сьогодні:</b> {stats.today}\n"
        f"<b>Цього тижня:</b> {stats.week}\n"
        f"<b>Цього місяця:</b> {stats.month}"
    )
    sent = await message.answer(text, parse_mode="HTML", reply_markup=admin_menu_keyboard())


@router.message(F.text == "💾 Експорт")
async def admin_btn_export(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    from bot.keyboards.inline import export_format_keyboard
    sent = await message.answer("Оберіть формат для експорту заявок:", reply_markup=export_format_keyboard())


@router.message(F.text == "📣 Розсилка")
async def admin_btn_broadcast(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    from aiogram.types import KeyboardButton
    from aiogram.utils.keyboard import ReplyKeyboardBuilder
    from bot.states import BroadcastStates

    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="❌ Скасувати"))
    kb = builder.as_markup(resize_keyboard=True, one_time_keyboard=True)

    await state.set_state(BroadcastStates.waiting_text)
    sent = await message.answer(
        "📢 <b>Нова розсилка</b>\n\nВведіть текст повідомлення:",
        parse_mode="HTML",
        reply_markup=kb,
    )


@router.message(F.text == "🩺 Звіти про укуси")
async def admin_btn_bites(message: Message, session: AsyncSession, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    from sqlalchemy import select
    from bot.models.models import BiteReport
    result = await session.execute(
        select(BiteReport).order_by(BiteReport.created_at.desc()).limit(20)
    )
    reports = result.scalars().all()

    if not reports:
        sent = await message.answer("🚨 Звітів про укуси ще немає.", reply_markup=admin_menu_keyboard())
        return

    sent = await message.answer(f"🚨 <b>Останні звіти про укуси ({len(reports)})</b>", parse_mode="HTML")
    for r in reports:
        created = r.created_at.strftime("%d.%m.%Y %H:%M") if r.created_at else "—"
        text = (
            f"🚨 <b>Звіт #{r.id}</b> від {created}\n"
            f"<b>Дата укусу:</b> {r.bite_date or '—'}\n"
            f"<b>Місце:</b> {r.location or '—'}\n"
            f"<b>Тварина:</b> {r.animal_description or '—'}\n"
            f"<b>Щеплена:</b> {r.vaccinated or '—'}\n"
            f"<b>Контакт:</b> {r.contact or '—'}"
        )
        sent = await message.answer(text, parse_mode="HTML")
    sent = await message.answer("Це останні 20 звітів.", reply_markup=admin_menu_keyboard())


# ---------------------------------------------------------------------------
# Користувацькі хендлери
# ---------------------------------------------------------------------------

@router.message(F.text == "🗂️ Мої заявки")
async def show_my_requests(message: Message, session: AsyncSession, state: FSMContext) -> None:
    user = await get_or_create_user(
        session=session,
        telegram_id=message.from_user.id,
        username=message.from_user.username,
    )
    requests = await get_user_requests(session=session, user_id=user.id)

    if not requests:
        sent = await message.answer("У вас ще немає заявок. Оберіть категорію, щоб подати першу!", reply_markup=smart_menu_keyboard(message.from_user.id))
        return

    sent = await message.answer(
        f"Ваші заявки ({len(requests)}):",
        reply_markup=user_requests_keyboard(requests),
    )


@router.callback_query(F.data.startswith("request:") & ~F.data.in_({"request:confirm", "request:cancel", "request:back_from_confirm"}))
async def show_request_detail(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    request_id = int(callback.data.split(":")[1])
    req = await get_request_by_id(session=session, request_id=request_id)

    if req is None:
        await callback.answer("Заявку не знайдено.", show_alert=True)
        return

    user = await get_or_create_user(
        session=session,
        telegram_id=callback.from_user.id,
        username=callback.from_user.username,
    )
    if req.user_id != user.id:
        await callback.answer("Немає доступу до цієї заявки.", show_alert=True)
        return

    category = CATEGORY_LABELS.get(req.category, req.category)
    status = STATUS_LABELS.get(req.status, req.status)
    location = format_location(req.latitude, req.longitude, req.address_text)
    created_at = req.created_at.strftime("%d.%m.%Y %H:%M") if req.created_at else "—"
    contact = req.contact or "Не вказано"

    text = (
        f"📋 <b>Заявка #{req.id}</b>\n\n"
        f"<b>Категорія:</b> {category}\n"
        f"<b>Статус:</b> {status}\n"
        f"<b>Опис:</b> {req.description}\n"
        f"<b>Локація:</b> {location}\n"
        f"<b>Контакт:</b> {contact}\n"
        f"<b>Дата:</b> {created_at}"
    )

    if req.admin_comment:
        text += f"\n\n💬 <b>Коментар адміна:</b> {req.admin_comment}"

    from bot.models.models import Category as CategoryEnum, Status as StatusEnum
    is_self_sterilization = (
        req.status == StatusEnum.AWAITING_FEEDBACK
        and req.category == CategoryEnum.STERILIZATION
        and req.description.startswith("[САМОСТІЙНА СТЕРИЛІЗАЦІЯ]")
    )

    if is_self_sterilization:
        text += (
            "\n\n⏳ <b>Очікується ваш фідбек!</b>\n"
            "Після завершення стерилізації натисніть кнопку нижче."
        )
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        builder = InlineKeyboardBuilder()
        builder.button(text="📝 Надати фідбек", callback_data=f"provide_feedback:{req.id}")
        builder.adjust(1)
        sent = await callback.message.answer(text, parse_mode="HTML", reply_markup=builder.as_markup())
    else:
        sent = await callback.message.answer(text, parse_mode="HTML")

    await callback.answer()


@router.message(F.text == "📖 Довідка та інформація")
async def show_info(message: Message, state: FSMContext) -> None:
    sent = await message.answer(INFO_TEXT, parse_mode="HTML", reply_markup=smart_menu_keyboard(message.from_user.id))


@router.message(F.text == "🏠 Меню")
async def show_menu(message: Message, state: FSMContext) -> None:
    if _is_admin(message.from_user.id):
        await state.clear()
        await message.answer("Головне меню:", reply_markup=admin_menu_keyboard())
        return

    fsm_data = await state.get_data()
    current_state = await state.get_state()

    from bot.states import RequestStates
    draft_states = {
        RequestStates.waiting_location,
        RequestStates.waiting_description,
        RequestStates.waiting_media,
        RequestStates.waiting_contact,
        RequestStates.confirming,
    }
    draft_state_values = {s.state for s in draft_states}

    if current_state in draft_state_values and fsm_data.get("category"):
        fsm_data["_is_draft"] = True
        await state.set_state(None)
        await state.set_data(fsm_data)
        sent = await message.answer(
            "🏠 Ви повернулись до головного меню.\n📝 Незавершена заявка збережена як чернетка.",
            reply_markup=main_menu_with_draft_keyboard(),
        )
        return

    has_draft = bool(fsm_data.get("_is_draft")) and bool(fsm_data.get("category"))
    if has_draft:
        sent = await message.answer("Головне меню:", reply_markup=main_menu_with_draft_keyboard())
    else:
        sent = await message.answer("Головне меню:", reply_markup=smart_menu_keyboard(message.from_user.id))


@router.message(F.text == "✏️ Продовжити незавершену заявку")
async def resume_draft(message: Message, state: FSMContext) -> None:
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    fsm_data = await state.get_data()
    if not fsm_data.get("_is_draft") or not fsm_data.get("category"):
        sent = await message.answer("Незавершених заявок немає.", reply_markup=smart_menu_keyboard(message.from_user.id))
        return


    from bot.models.models import Category
    from bot.utils.formatters import CATEGORY_LABELS
    category = Category(fsm_data["category"])
    description = fsm_data.get("description", "не вказано")
    media_count = len(fsm_data.get("media", []))

    text = (
        f"📝 <b>Незавершена заявка:</b>\n\n"
        f"<b>Категорія:</b> {CATEGORY_LABELS[category]}\n"
        f"<b>Опис:</b> {description[:80] + '…' if len(description) > 80 else description}\n"
        f"<b>Медіафайлів:</b> {media_count}\n\n"
        f"Що бажаєте зробити?"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="▶️ Продовжити заповнення", callback_data="draft:continue")
    builder.button(text="🗑 Видалити чернетку", callback_data="draft:delete")
    builder.adjust(1)

    sent1 = await message.answer(text, parse_mode="HTML", reply_markup=main_menu_with_draft_keyboard())
    sent2 = await message.answer("Оберіть дію:", reply_markup=builder.as_markup())


@router.callback_query(F.data == "draft:delete")
async def draft_delete(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=None)
    sent = await callback.message.answer("🗑 Чернетку видалено.", reply_markup=smart_menu_keyboard(callback.from_user.id))
    await callback.answer()


@router.callback_query(F.data == "draft:continue")
async def draft_continue(callback: CallbackQuery, state: FSMContext) -> None:
    from bot.handlers.request import (
        _contact_keyboard, _description_keyboard,
        _location_keyboard, _media_keyboard, _show_confirmation,
    )
    from bot.states import RequestStates

    fsm_data = await state.get_data()
    await state.update_data(_is_draft=False)

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer()

    if not fsm_data.get("latitude") and not fsm_data.get("address_text"):
        await state.set_state(RequestStates.waiting_location)
        sent = await callback.message.answer("📍 Надішліть геолокацію або введіть адресу:", reply_markup=_location_keyboard())
    elif not fsm_data.get("description"):
        await state.set_state(RequestStates.waiting_description)
        sent = await callback.message.answer("📝 Опишіть ситуацію (мінімум 10 символів):", reply_markup=_description_keyboard())
    elif not fsm_data.get("contact"):
        count = len(fsm_data.get("media", []))
        await state.set_state(RequestStates.waiting_media)
        sent = await callback.message.answer("📷 Надішліть фото/відео або пропустіть:", reply_markup=_media_keyboard(count))
    else:
        await _show_confirmation(callback.message, state)
        return

