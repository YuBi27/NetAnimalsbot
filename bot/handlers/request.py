"""FSM-обробники для подання заявки про тварину."""

import logging

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.keyboards.inline import admin_request_keyboard
from bot.keyboards.reply import contact_keyboard, main_menu_keyboard, smart_menu_keyboard
from bot.middlewares.throttle import increment_spam_counter
from bot.models.models import Category
from bot.repositories.user_repo import get_or_create_user
from bot.services.request_service import RequestService
from bot.states import RequestStates
from bot.utils.formatters import CATEGORY_LABELS, format_admin_message
from bot.utils.maps import make_maps_link
from bot.utils.validators import validate_description, validate_media_count

logger = logging.getLogger(__name__)

router = Router()

_CATEGORY_MAP: dict[str, Category] = {
    "🐾 Загублена тварина — подати заявку": Category.LOST,
    "🚑 Поранена або хвора тварина": Category.INJURED,
    "💉 Запит на стерилізацію": Category.STERILIZATION,
    "🐺 Агресивна тварина на вулиці": Category.AGGRESSIVE,
    "🪦 Виявлено мертву тварину": Category.DEAD,
}

_MAX_MEDIA = 5


# ---------------------------------------------------------------------------
# Клавіатури з кнопкою "Назад"
# ---------------------------------------------------------------------------

def _location_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="📍 Поділитися геолокацією", request_location=True))
    builder.row(KeyboardButton(text="Ввести адресу текстом"))
    builder.row(KeyboardButton(text="🏠 Меню"), KeyboardButton(text="❌ Скасувати"))
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)


def _description_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="◀️ Назад"), KeyboardButton(text="❌ Скасувати"))
    builder.row(KeyboardButton(text="🏠 Меню"))
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)


def _media_keyboard(count: int) -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    if count > 0:
        builder.row(KeyboardButton(text="➡️ Далі"))
    builder.row(KeyboardButton(text="⏭ Пропустити медіа"))
    builder.row(KeyboardButton(text="◀️ Назад"), KeyboardButton(text="❌ Скасувати"))
    builder.row(KeyboardButton(text="🏠 Меню"))
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)


def _contact_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="📱 Поділитися контактом", request_contact=True))
    builder.row(KeyboardButton(text="Ввести @username"))
    builder.row(KeyboardButton(text="◀️ Назад"), KeyboardButton(text="❌ Скасувати"))
    builder.row(KeyboardButton(text="🏠 Меню"))
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)


# ---------------------------------------------------------------------------
# Крок 1: Вибір категорії
# ---------------------------------------------------------------------------

@router.message(F.text.in_(_CATEGORY_MAP))
async def start_request(message: Message, state: FSMContext) -> None:
    category = _CATEGORY_MAP[message.text]
    await state.set_state(RequestStates.waiting_location)
    await state.update_data(category=category.value, media=[])

    await message.answer(
        f"Ви обрали: <b>{CATEGORY_LABELS[category]}</b>\n\n"
        "📍 Надішліть геолокацію або введіть адресу текстом:",
        reply_markup=_location_keyboard(),
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# Крок 2: Локація
# ---------------------------------------------------------------------------

@router.message(RequestStates.waiting_location, F.location)
async def process_location_geo(message: Message, state: FSMContext) -> None:
    await state.update_data(
        latitude=message.location.latitude,
        longitude=message.location.longitude,
        address_text=None,
    )
    await state.set_state(RequestStates.waiting_description)
    await message.answer(
        "✅ Геолокацію отримано.\n\n📝 Опишіть ситуацію (мінімум 10 символів):",
        reply_markup=_description_keyboard(),
    )


@router.message(RequestStates.waiting_location, F.text & ~F.text.in_({"❌ Скасувати", "🏠 Меню"}))
async def process_location_text(message: Message, state: FSMContext) -> None:
    await state.update_data(latitude=None, longitude=None, address_text=message.text.strip())
    await state.set_state(RequestStates.waiting_description)
    await message.answer(
        "✅ Адресу збережено.\n\n📝 Опишіть ситуацію (мінімум 10 символів):",
        reply_markup=_description_keyboard(),
    )


# ---------------------------------------------------------------------------
# Крок 3: Опис
# ---------------------------------------------------------------------------

@router.message(RequestStates.waiting_description, F.text == "◀️ Назад")
async def back_to_location(message: Message, state: FSMContext) -> None:
    await state.set_state(RequestStates.waiting_location)
    await message.answer(
        "📍 Надішліть геолокацію або введіть адресу текстом:",
        reply_markup=_location_keyboard(),
    )


@router.message(RequestStates.waiting_description, F.text & ~F.text.in_({"◀️ Назад", "❌ Скасувати", "🏠 Меню"}))
async def process_description(message: Message, state: FSMContext) -> None:
    text = message.text.strip()
    if not validate_description(text):
        await message.answer("⚠️ Опис занадто короткий. Введіть щонайменше 10 символів:")
        return
    await state.update_data(description=text)
    await state.set_state(RequestStates.waiting_media)
    fsm_data = await state.get_data()
    count = len(fsm_data.get("media", []))
    await message.answer(
        "✅ Опис збережено.\n\n📷 Надішліть фото або відео (до 5 файлів), або пропустіть:",
        reply_markup=_media_keyboard(count),
    )


# ---------------------------------------------------------------------------
# Крок 4: Медіа
# ---------------------------------------------------------------------------

@router.message(RequestStates.waiting_media, F.text == "◀️ Назад")
async def back_to_description(message: Message, state: FSMContext) -> None:
    await state.set_state(RequestStates.waiting_description)
    await message.answer(
        "📝 Введіть опис ситуації (мінімум 10 символів):",
        reply_markup=_description_keyboard(),
    )


@router.message(RequestStates.waiting_media, F.photo | F.video)
async def process_media(message: Message, state: FSMContext) -> None:
    fsm_data = await state.get_data()
    media: list[dict] = fsm_data.get("media", [])

    if not validate_media_count(len(media)):
        await message.answer(f"⚠️ Досягнуто ліміт {_MAX_MEDIA} файлів. Натисніть «➡️ Далі».")
        return

    if message.photo:
        media.append({"file_id": message.photo[-1].file_id, "type": "photo"})
    else:
        media.append({"file_id": message.video.file_id, "type": "video"})

    await state.update_data(media=media)
    remaining = _MAX_MEDIA - len(media)

    if remaining > 0:
        await message.answer(
            f"✅ Файл додано ({len(media)}/{_MAX_MEDIA}). Ще {remaining} або натисніть «➡️ Далі»:",
            reply_markup=_media_keyboard(len(media)),
        )
    else:
        await state.set_state(RequestStates.waiting_contact)
        await message.answer(
            f"✅ Додано {_MAX_MEDIA} файлів.\n\n📱 Поділіться контактом або введіть @username:",
            reply_markup=_contact_keyboard(),
        )


@router.message(RequestStates.waiting_media, F.text.in_({"⏭ Пропустити медіа", "➡️ Далі"}))
async def skip_media(message: Message, state: FSMContext) -> None:
    await state.set_state(RequestStates.waiting_contact)
    await message.answer(
        "📱 Поділіться контактом або введіть @username:",
        reply_markup=_contact_keyboard(),
    )


# ---------------------------------------------------------------------------
# Крок 5: Контакт
# ---------------------------------------------------------------------------

@router.message(RequestStates.waiting_contact, F.text == "◀️ Назад")
async def back_to_media(message: Message, state: FSMContext) -> None:
    await state.set_state(RequestStates.waiting_media)
    fsm_data = await state.get_data()
    count = len(fsm_data.get("media", []))
    await message.answer(
        "📷 Надішліть фото або відео (до 5 файлів), або пропустіть:",
        reply_markup=_media_keyboard(count),
    )


@router.message(RequestStates.waiting_contact, F.contact)
async def process_contact_shared(message: Message, state: FSMContext) -> None:
    c = message.contact
    name = f"{c.first_name or ''} {c.last_name or ''}".strip()
    contact_str = f"{name} ({c.phone_number})" if name else c.phone_number
    await state.update_data(contact=contact_str)
    await _show_confirmation(message, state)


@router.message(RequestStates.waiting_contact, F.text & ~F.text.in_({"◀️ Назад", "❌ Скасувати", "🏠 Меню"}))
async def process_contact_text(message: Message, state: FSMContext) -> None:
    await state.update_data(contact=message.text.strip())
    await _show_confirmation(message, state)


# ---------------------------------------------------------------------------
# Крок 6: Підтвердження
# ---------------------------------------------------------------------------

async def _show_confirmation(message: Message, state: FSMContext) -> None:
    fsm_data = await state.get_data()
    await state.set_state(RequestStates.confirming)

    category = Category(fsm_data["category"])
    lat = fsm_data.get("latitude")
    lon = fsm_data.get("longitude")
    address_text = fsm_data.get("address_text")

    if lat is not None and lon is not None:
        location_str = make_maps_link(lat, lon)
        if address_text:
            location_str += f"\n{address_text}"
    elif address_text:
        location_str = address_text
    else:
        location_str = "Не вказано"

    summary = (
        f"📋 <b>Перевірте вашу заявку:</b>\n\n"
        f"<b>Категорія:</b> {CATEGORY_LABELS[category]}\n"
        f"<b>Опис:</b> {fsm_data.get('description', '—')}\n"
        f"<b>Локація:</b> {location_str}\n"
        f"<b>Контакт:</b> {fsm_data.get('contact', 'Не вказано')}\n"
        f"<b>Медіафайлів:</b> {len(fsm_data.get('media', []))}"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Відправити", callback_data="request:confirm")
    builder.button(text="◀️ Назад", callback_data="request:back_from_confirm")
    builder.button(text="❌ Скасувати", callback_data="request:cancel")
    builder.adjust(1)

    await message.answer("⏳", reply_markup=ReplyKeyboardRemove())
    await message.answer(summary, reply_markup=builder.as_markup(), parse_mode="HTML")


@router.callback_query(RequestStates.confirming, F.data == "request:back_from_confirm")
async def back_from_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    """Повернення з підтвердження до кроку контакту."""
    await state.set_state(RequestStates.waiting_contact)
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.message.answer(
        "📱 Поділіться контактом або введіть @username:",
        reply_markup=_contact_keyboard(),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Скасування на будь-якому кроці
# ---------------------------------------------------------------------------

@router.message(
    F.text == "❌ Скасувати",
    StateFilter(
        RequestStates.waiting_location,
        RequestStates.waiting_description,
        RequestStates.waiting_media,
        RequestStates.waiting_contact,
    ),
)
async def cancel_request_reply(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("❌ Заявку скасовано.", reply_markup=smart_menu_keyboard(message.from_user.id))


@router.callback_query(F.data == "request:cancel")
async def cancel_request(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.message.answer("❌ Заявку скасовано.", reply_markup=smart_menu_keyboard(callback.from_user.id))
    await callback.answer()


# ---------------------------------------------------------------------------
# Підтвердження та збереження
# ---------------------------------------------------------------------------

@router.callback_query(RequestStates.confirming, F.data == "request:confirm")
async def confirm_request(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    bot_instance: Bot,
    redis,
) -> None:
    fsm_data = await state.get_data()

    user = await get_or_create_user(
        session=session,
        telegram_id=callback.from_user.id,
        username=callback.from_user.username,
    )

    category = Category(fsm_data["category"])
    lat = fsm_data.get("latitude")
    lon = fsm_data.get("longitude")
    address_text = fsm_data.get("address_text")
    media_files: list[dict] = fsm_data.get("media", [])

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
        description=fsm_data.get("description", ""),
        location=location,
        media_files=media_files,
        contact=fsm_data.get("contact"),
    )

    admin_text = format_admin_message(req, user)
    is_admin_submitting = callback.from_user.id in settings.all_admin_ids
    for admin_id in settings.all_admin_ids:
        # Не надсилаємо сповіщення адміну якщо він сам подає заявку
        if is_admin_submitting and admin_id == callback.from_user.id:
            continue
        try:
            await bot_instance.send_message(
                chat_id=admin_id,
                text=admin_text,
                reply_markup=admin_request_keyboard(req.id),
                parse_mode="HTML",
            )
            for mf in media_files:
                try:
                    if mf["type"] == "photo":
                        await bot_instance.send_photo(chat_id=admin_id, photo=mf["file_id"])
                    else:
                        await bot_instance.send_video(chat_id=admin_id, video=mf["file_id"])
                except Exception as exc:
                    logger.warning("Failed to forward media to admin %s: %s", admin_id, exc)
        except Exception as exc:
            logger.error("Failed to send admin notification to %s: %s", admin_id, exc)

    try:
        await service.publish_to_channel(req, settings.CHANNEL_ID)
    except Exception as exc:
        logger.warning("Failed to publish to channel: %s", exc)

    if redis is not None:
        await increment_spam_counter(redis, callback.from_user.id)

    await state.clear()

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    await callback.message.answer(
        f"✅ Заявку <b>#{req.id}</b> успішно подано!\nМи розглянемо її найближчим часом.",
        reply_markup=smart_menu_keyboard(callback.from_user.id),
        parse_mode="HTML",
    )
    await callback.answer()
