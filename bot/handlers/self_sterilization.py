"""Обробники для самостійної стерилізації та фідбеку."""

import logging

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, KeyboardButton, Message, ReplyKeyboardMarkup, ReplyKeyboardRemove
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.keyboards.inline import admin_request_keyboard
from bot.keyboards.reply import main_menu_keyboard, smart_menu_keyboard
from bot.models.models import Category, MediaType, Status
from bot.repositories.media_repo import add_media
from bot.repositories.request_repo import get_request_by_id
from bot.repositories.user_repo import get_or_create_user
from bot.services.request_service import RequestService
from bot.states import FeedbackStates, SelfSterilizationStates
from bot.utils.formatters import CATEGORY_LABELS, format_admin_message
from bot.utils.validators import validate_description, validate_media_count

logger = logging.getLogger(__name__)

router = Router()

_MAX_MEDIA = 5


# ---------------------------------------------------------------------------
# Клавіатури
# ---------------------------------------------------------------------------

def _description_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="❌ Скасувати"))
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
# Початок заявки "Стерилізую самостійно"
# ---------------------------------------------------------------------------

@router.message(F.text == "🔬 Стерилізую самостійно")
async def start_self_sterilization(message: Message, state: FSMContext) -> None:
    """Початок заявки на самостійну стерилізацію."""
    await state.set_state(SelfSterilizationStates.waiting_description)
    await state.update_data(media=[])

    await message.answer(
        "🏥 <b>Заявка на самостійну стерилізацію</b>\n\n"
        "Ви плануєте стерилізувати тварину самостійно і потребуєте дозволу.\n\n"
        "📝 Опишіть тварину (порода, колір, особливі прикмети, мінімум 10 символів):",
        reply_markup=_description_keyboard(),
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# Крок 1: Опис
# ---------------------------------------------------------------------------

@router.message(SelfSterilizationStates.waiting_description, F.text & ~F.text.in_({"❌ Скасувати", "🏠 Меню"}))
async def process_self_sterilization_description(message: Message, state: FSMContext) -> None:
    text = message.text.strip()
    if not validate_description(text):
        await message.answer("⚠️ Опис занадто короткий. Введіть щонайменше 10 символів:")
        return
    await state.update_data(description=text)
    await state.set_state(SelfSterilizationStates.waiting_media)
    await message.answer(
        "✅ Опис збережено.\n\n📷 Надішліть фото тварини (до 5 файлів).\n"
        "<b>Фото обов'язкове для розгляду заявки!</b>",
        reply_markup=_media_keyboard(0),
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# Крок 2: Медіа (обов'язково хоча б 1 фото)
# ---------------------------------------------------------------------------

@router.message(SelfSterilizationStates.waiting_media, F.text == "◀️ Назад")
async def back_to_self_sterilization_description(message: Message, state: FSMContext) -> None:
    await state.set_state(SelfSterilizationStates.waiting_description)
    await message.answer(
        "📝 Опишіть тварину (мінімум 10 символів):",
        reply_markup=_description_keyboard(),
    )


@router.message(SelfSterilizationStates.waiting_media, F.photo | F.video)
async def process_self_sterilization_media(message: Message, state: FSMContext) -> None:
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
        await state.set_state(SelfSterilizationStates.waiting_contact)
        await message.answer(
            f"✅ Додано {_MAX_MEDIA} файлів.\n\n📱 Поділіться контактом або введіть @username:",
            reply_markup=_contact_keyboard(),
        )


@router.message(SelfSterilizationStates.waiting_media, F.text.in_({"⏭ Пропустити медіа", "➡️ Далі"}))
async def skip_self_sterilization_media(message: Message, state: FSMContext) -> None:
    fsm_data = await state.get_data()
    media: list[dict] = fsm_data.get("media", [])
    
    if len(media) == 0:
        await message.answer("⚠️ Для заявки на самостійну стерилізацію потрібно хоча б одне фото тварини!")
        return
    
    await state.set_state(SelfSterilizationStates.waiting_contact)
    await message.answer(
        "📱 Поділіться контактом або введіть @username:",
        reply_markup=_contact_keyboard(),
    )


# ---------------------------------------------------------------------------
# Крок 3: Контакт
# ---------------------------------------------------------------------------

@router.message(SelfSterilizationStates.waiting_contact, F.text == "◀️ Назад")
async def back_to_self_sterilization_media(message: Message, state: FSMContext) -> None:
    await state.set_state(SelfSterilizationStates.waiting_media)
    fsm_data = await state.get_data()
    count = len(fsm_data.get("media", []))
    await message.answer(
        "📷 Надішліть фото або відео (до 5 файлів):",
        reply_markup=_media_keyboard(count),
    )


@router.message(SelfSterilizationStates.waiting_contact, F.contact)
async def process_self_sterilization_contact_shared(message: Message, state: FSMContext) -> None:
    c = message.contact
    name = f"{c.first_name or ''} {c.last_name or ''}".strip()
    contact_str = f"{name} ({c.phone_number})" if name else c.phone_number
    await state.update_data(contact=contact_str)
    await _show_self_sterilization_confirmation(message, state)


@router.message(SelfSterilizationStates.waiting_contact, F.text & ~F.text.in_({"◀️ Назад", "❌ Скасувати", "🏠 Меню"}))
async def process_self_sterilization_contact_text(message: Message, state: FSMContext) -> None:
    await state.update_data(contact=message.text.strip())
    await _show_self_sterilization_confirmation(message, state)


# ---------------------------------------------------------------------------
# Крок 4: Підтвердження
# ---------------------------------------------------------------------------

async def _show_self_sterilization_confirmation(message: Message, state: FSMContext) -> None:
    fsm_data = await state.get_data()
    await state.set_state(SelfSterilizationStates.confirming)

    summary = (
        f"📋 <b>Перевірте вашу заявку:</b>\n\n"
        f"<b>Тип:</b> Самостійна стерилізація\n"
        f"<b>Опис тварини:</b> {fsm_data.get('description', '—')}\n"
        f"<b>Контакт:</b> {fsm_data.get('contact', 'Не вказано')}\n"
        f"<b>Медіафайлів:</b> {len(fsm_data.get('media', []))}"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Відправити", callback_data="self_sterilization:confirm")
    builder.button(text="◀️ Назад", callback_data="self_sterilization:back")
    builder.button(text="❌ Скасувати", callback_data="self_sterilization:cancel")
    builder.adjust(1)

    await message.answer(summary, reply_markup=builder.as_markup(), parse_mode="HTML")


@router.callback_query(SelfSterilizationStates.confirming, F.data == "self_sterilization:back")
async def back_from_self_sterilization_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SelfSterilizationStates.waiting_contact)
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.message.answer(
        "📱 Поділіться контактом або введіть @username:",
        reply_markup=_contact_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "self_sterilization:cancel")
async def cancel_self_sterilization(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.message.answer("❌ Заявку скасовано.", reply_markup=smart_menu_keyboard(callback.from_user.id))
    await callback.answer()


@router.callback_query(SelfSterilizationStates.confirming, F.data == "self_sterilization:confirm")
async def confirm_self_sterilization(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    bot_instance: Bot,
) -> None:
    """Створюємо заявку на самостійну стерилізацію."""
    fsm_data = await state.get_data()

    user = await get_or_create_user(
        session=session,
        telegram_id=callback.from_user.id,
        username=callback.from_user.username,
    )

    media_files: list[dict] = fsm_data.get("media", [])

    service = RequestService(session=session, bot=bot_instance)
    req = await service.create_request(
        user_id=user.id,
        category=Category.STERILIZATION,
        description=f"[САМОСТІЙНА СТЕРИЛІЗАЦІЯ] {fsm_data.get('description', '')}",
        location=None,
        media_files=media_files,
        contact=fsm_data.get("contact"),
    )

    # Сповіщення адміну
    admin_text = format_admin_message(req, user)
    admin_text += "\n\n⚠️ <b>Це заявка на САМОСТІЙНУ стерилізацію!</b>\nПотребує погодження."

    # Кнопка для адміна — погодити (IN_PROGRESS → AWAITING_FEEDBACK)
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Погодити", callback_data=f"approve_self_sterilization:{req.id}")
    builder.button(text="❌ Відхилити", callback_data=f"status:rejected:{req.id}")
    builder.adjust(1)

    for admin_id in settings.all_admin_ids:
        try:
            await bot_instance.send_message(
                chat_id=admin_id,
                text=admin_text,
                reply_markup=builder.as_markup(),
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

    await state.clear()

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    await callback.message.answer(
        f"✅ Заявку <b>#{req.id}</b> на самостійну стерилізацію подано!\n\n"
        "Очікуйте погодження від адміністратора. Після погодження ви зможете надати фідбек після завершення процедури.",
        reply_markup=smart_menu_keyboard(message.from_user.id),
        parse_mode="HTML",
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Адмін погоджує самостійну стерилізацію
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("approve_self_sterilization:"))
async def approve_self_sterilization(
    callback: CallbackQuery,
    session: AsyncSession,
    bot_instance: Bot,
) -> None:
    """Адмін погоджує заявку — статус → AWAITING_FEEDBACK."""
    if callback.from_user.id not in settings.all_admin_ids:
        await callback.answer("Немає доступу.", show_alert=True)
        return

    request_id = int(callback.data.split(":")[1])
    
    service = RequestService(session=session, bot=bot_instance)
    try:
        # Спочатку IN_PROGRESS
        req = await service.change_status(request_id, Status.IN_PROGRESS, notify=False)
        # Потім AWAITING_FEEDBACK
        req = await service.change_status(request_id, Status.AWAITING_FEEDBACK, notify=False)
    except ValueError as exc:
        await callback.answer(str(exc), show_alert=True)
        return

    # Сповіщення користувачу
    from sqlalchemy import select
    from bot.models.models import User
    result = await session.execute(select(User).where(User.id == req.user_id))
    user = result.scalar_one_or_none()

    if user:
        user_text = (
            f"✅ Вашу заявку <b>#{req.id}</b> на самостійну стерилізацію <b>погоджено</b>!\n\n"
            "Після завершення процедури стерилізації, будь ласка, надайте фідбек через меню «🗂️ Мої заявки»."
        )
        try:
            await bot_instance.send_message(
                chat_id=user.telegram_id,
                text=user_text,
                parse_mode="HTML",
            )
        except Exception as exc:
            logger.warning("Failed to notify user: %s", exc)

    await callback.answer("✅ Заявку погоджено!")
    try:
        await callback.message.edit_text(
            f"{callback.message.text}\n\n✅ <b>ПОГОДЖЕНО</b> — очікується фідбек від користувача.",
            parse_mode="HTML",
            reply_markup=None,
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Користувач надає фідбек після стерилізації
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("provide_feedback:"))
async def start_feedback(callback: CallbackQuery, state: FSMContext) -> None:
    """Користувач натискає кнопку 'Надати фідбек' у своїх заявках."""
    request_id = int(callback.data.split(":")[1])
    
    await state.set_state(FeedbackStates.waiting_description)
    await state.update_data(request_id=request_id, feedback_media=[])
    
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        "📝 <b>Фідбек після стерилізації</b>\n\n"
        "Опишіть як пройшла процедура, стан тварини (мінімум 10 символів):",
        reply_markup=_description_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(FeedbackStates.waiting_description, F.text & ~F.text.in_({"❌ Скасувати", "🏠 Меню"}))
async def process_feedback_description(message: Message, state: FSMContext) -> None:
    text = message.text.strip()
    if not validate_description(text):
        await message.answer("⚠️ Опис занадто короткий. Введіть щонайменше 10 символів:")
        return
    await state.update_data(feedback_description=text)
    await state.set_state(FeedbackStates.waiting_media)
    await message.answer(
        "✅ Опис збережено.\n\n📷 Надішліть фото або відео після стерилізації (до 5 файлів), або пропустіть:",
        reply_markup=_media_keyboard(0),
    )


@router.message(FeedbackStates.waiting_media, F.text == "◀️ Назад")
async def back_to_feedback_description(message: Message, state: FSMContext) -> None:
    await state.set_state(FeedbackStates.waiting_description)
    await message.answer(
        "📝 Опишіть як пройшла процедура:",
        reply_markup=_description_keyboard(),
    )


@router.message(FeedbackStates.waiting_media, F.photo | F.video)
async def process_feedback_media(message: Message, state: FSMContext) -> None:
    fsm_data = await state.get_data()
    media: list[dict] = fsm_data.get("feedback_media", [])

    if not validate_media_count(len(media)):
        await message.answer(f"⚠️ Досягнуто ліміт {_MAX_MEDIA} файлів. Натисніть «➡️ Далі».")
        return

    if message.photo:
        media.append({"file_id": message.photo[-1].file_id, "type": "photo"})
    else:
        media.append({"file_id": message.video.file_id, "type": "video"})

    await state.update_data(feedback_media=media)
    remaining = _MAX_MEDIA - len(media)

    if remaining > 0:
        await message.answer(
            f"✅ Файл додано ({len(media)}/{_MAX_MEDIA}). Ще {remaining} або натисніть «➡️ Далі»:",
            reply_markup=_media_keyboard(len(media)),
        )
    else:
        await _show_feedback_confirmation(message, state)


@router.message(FeedbackStates.waiting_media, F.text.in_({"⏭ Пропустити медіа", "➡️ Далі"}))
async def skip_feedback_media(message: Message, state: FSMContext) -> None:
    await _show_feedback_confirmation(message, state)


async def _show_feedback_confirmation(message: Message, state: FSMContext) -> None:
    fsm_data = await state.get_data()
    await state.set_state(FeedbackStates.confirming)

    summary = (
        f"📋 <b>Перевірте ваш фідбек:</b>\n\n"
        f"<b>Опис:</b> {fsm_data.get('feedback_description', '—')}\n"
        f"<b>Медіафайлів:</b> {len(fsm_data.get('feedback_media', []))}"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Відправити", callback_data="feedback:confirm")
    builder.button(text="◀️ Назад", callback_data="feedback:back")
    builder.button(text="❌ Скасувати", callback_data="feedback:cancel")
    builder.adjust(1)

    await message.answer(summary, reply_markup=builder.as_markup(), parse_mode="HTML")


@router.callback_query(FeedbackStates.confirming, F.data == "feedback:back")
async def back_from_feedback_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(FeedbackStates.waiting_media)
    fsm_data = await state.get_data()
    count = len(fsm_data.get("feedback_media", []))
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.message.answer(
        "📷 Надішліть фото або відео:",
        reply_markup=_media_keyboard(count),
    )
    await callback.answer()


@router.callback_query(F.data == "feedback:cancel")
async def cancel_feedback(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.message.answer("❌ Фідбек скасовано.", reply_markup=smart_menu_keyboard(callback.from_user.id))
    await callback.answer()


@router.callback_query(FeedbackStates.confirming, F.data == "feedback:confirm")
async def confirm_feedback(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    bot_instance: Bot,
) -> None:
    """Зберігаємо фідбек, додаємо медіа, змінюємо статус на DONE."""
    fsm_data = await state.get_data()
    request_id: int = fsm_data["request_id"]
    feedback_description: str = fsm_data.get("feedback_description", "")
    feedback_media: list[dict] = fsm_data.get("feedback_media", [])

    req = await get_request_by_id(session, request_id)
    if req is None:
        await callback.answer("Заявку не знайдено.", show_alert=True)
        await state.clear()
        return

    # Зберігаємо фідбек
    req.feedback_text = feedback_description
    await session.flush()

    # Додаємо медіа фідбеку до заявки
    for mf in feedback_media:
        media_type = MediaType(mf["type"])
        await add_media(session, req.id, mf["file_id"], media_type)

    # Змінюємо статус на DONE
    service = RequestService(session=session, bot=bot_instance)
    try:
        req = await service.change_status(request_id, Status.DONE, notify=False)
    except ValueError as exc:
        await callback.answer(str(exc), show_alert=True)
        await state.clear()
        return

    # Сповіщення всім адмінам про фідбек
    admin_text = (
        f"✅ <b>Фідбек отримано!</b>\n\n"
        f"<b>Заявка:</b> #{req.id}\n"
        f"<b>Категорія:</b> Самостійна стерилізація\n"
        f"<b>Опис тварини:</b> {req.description}\n\n"
        f"<b>Фідбек користувача:</b>\n{feedback_description}\n\n"
        f"Заявка автоматично закрита."
    )

    for admin_id in settings.all_admin_ids:
        try:
            await bot_instance.send_message(
                chat_id=admin_id,
                text=admin_text,
                parse_mode="HTML",
            )
            for mf in feedback_media:
                try:
                    if mf["type"] == "photo":
                        await bot_instance.send_photo(chat_id=admin_id, photo=mf["file_id"])
                    else:
                        await bot_instance.send_video(chat_id=admin_id, video=mf["file_id"])
                except Exception as exc:
                    logger.warning("Failed to send feedback media to admin %s: %s", admin_id, exc)
        except Exception as exc:
            logger.error("Failed to notify admin %s about feedback: %s", admin_id, exc)

    await state.clear()

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    await callback.message.answer(
        f"✅ Дякуємо за фідбек!\n\nЗаявку <b>#{req.id}</b> закрито. Інформація про стерилізацію збережена.",
        reply_markup=smart_menu_keyboard(message.from_user.id),
        parse_mode="HTML",
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Скасування
# ---------------------------------------------------------------------------

@router.message(F.text == "❌ Скасувати")
async def cancel_any(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("❌ Дію скасовано.", reply_markup=smart_menu_keyboard(message.from_user.id))
