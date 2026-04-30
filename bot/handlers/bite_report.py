"""FSM-обробник для звітів про укуси агресивних тварин."""

import logging

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, KeyboardButton, Message, ReplyKeyboardMarkup, ReplyKeyboardRemove
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.keyboards.reply import main_menu_keyboard, smart_menu_keyboard
from bot.models.models import BiteReport
from bot.repositories.user_repo import get_or_create_user
from bot.states import BiteReportStates

logger = logging.getLogger(__name__)
router = Router()

# Інформація про хвороби після укусу
BITE_INFO = (
    "⚠️ <b>Важлива інформація після укусу тварини</b>\n\n"
    "🦠 <b>Можливі захворювання:</b>\n"
    "• <b>Сказ</b> — смертельно небезпечне вірусне захворювання. "
    "Симптоми можуть з'явитися через 10 днів — 3 місяці після укусу.\n"
    "• <b>Правець</b> — небезпечна бактеріальна інфекція.\n"
    "• <b>Пастерельоз</b> — бактеріальна інфекція від укусу.\n\n"
    "🏥 <b>Що робити НЕГАЙНО:</b>\n"
    "1️⃣ Промийте рану водою з милом протягом 15 хвилин\n"
    "2️⃣ Обробіть рану антисептиком\n"
    "3️⃣ Зверніться до лікаря або травмпункту\n"
    "4️⃣ Повідомте про укус ветеринарну службу\n\n"
    "💉 <b>Щеплення від сказу</b> необхідно зробити якомога швидше!\n\n"
    "📞 <b>Екстрена допомога:</b> 103\n"
    "🏥 <b>Травмпункт:</b> зверніться до найближчого медзакладу"
)


def _cancel_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="❌ Скасувати"))
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)


def _vaccinated_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(
        KeyboardButton(text="✅ Так, щеплена"),
        KeyboardButton(text="❌ Ні / Невідомо"),
    )
    builder.row(KeyboardButton(text="❌ Скасувати"))
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)


def _contact_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="📱 Поділитися контактом", request_contact=True))
    builder.row(KeyboardButton(text="Ввести @username або телефон"))
    builder.row(KeyboardButton(text="❌ Скасувати"))
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)


@router.message(F.text == "🩸 Мене вкусила тварина")
async def start_bite_report(message: Message, state: FSMContext) -> None:
    """Початок FSM звіту про укус."""
    # Спочатку надсилаємо важливу інформацію
    await message.answer(BITE_INFO, parse_mode="HTML")
    await message.answer(
        "📋 <b>Заповніть звіт про укус</b>\n\n"
        "Це допоможе нам відстежити агресивних тварин та захистити інших мешканців.\n\n"
        "📅 Вкажіть дату укусу (наприклад: 12.04.2026):",
        parse_mode="HTML",
        reply_markup=_cancel_keyboard(),
    )
    await state.set_state(BiteReportStates.waiting_date)


@router.message(BiteReportStates.waiting_date, F.text == "❌ Скасувати")
@router.message(BiteReportStates.waiting_location, F.text == "❌ Скасувати")
@router.message(BiteReportStates.waiting_animal_description, F.text == "❌ Скасувати")
@router.message(BiteReportStates.waiting_vaccinated, F.text == "❌ Скасувати")
@router.message(BiteReportStates.waiting_contact, F.text == "❌ Скасувати")
async def cancel_bite_report(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Звіт скасовано.", reply_markup=smart_menu_keyboard(message.from_user.id))


@router.message(BiteReportStates.waiting_date, F.text)
async def process_bite_date(message: Message, state: FSMContext) -> None:
    await state.update_data(bite_date=message.text.strip())
    await state.set_state(BiteReportStates.waiting_location)
    await message.answer(
        "📍 Де стався укус? Вкажіть адресу або місце:",
        reply_markup=_cancel_keyboard(),
    )


@router.message(BiteReportStates.waiting_location, F.text)
async def process_bite_location(message: Message, state: FSMContext) -> None:
    await state.update_data(bite_location=message.text.strip())
    await state.set_state(BiteReportStates.waiting_animal_description)
    await message.answer(
        "🐕 Опишіть тварину (вид, колір, розмір, особливі прикмети):",
        reply_markup=_cancel_keyboard(),
    )


@router.message(BiteReportStates.waiting_animal_description, F.text)
async def process_animal_description(message: Message, state: FSMContext) -> None:
    await state.update_data(animal_description=message.text.strip())
    await state.set_state(BiteReportStates.waiting_vaccinated)
    await message.answer(
        "💉 Чи була тварина щеплена від сказу (якщо відомо)?",
        reply_markup=_vaccinated_keyboard(),
    )


@router.message(BiteReportStates.waiting_vaccinated, F.text.in_({"✅ Так, щеплена", "❌ Ні / Невідомо"}))
async def process_vaccinated(message: Message, state: FSMContext) -> None:
    vaccinated = "Так" if message.text == "✅ Так, щеплена" else "Ні / Невідомо"
    await state.update_data(vaccinated=vaccinated)
    await state.set_state(BiteReportStates.waiting_contact)
    await message.answer(
        "📱 Вкажіть ваш контакт для зв'язку (телефон або @username):",
        reply_markup=_contact_keyboard(),
    )


@router.message(BiteReportStates.waiting_contact, F.contact)
async def process_bite_contact_shared(message: Message, state: FSMContext, session: AsyncSession, bot_instance: Bot) -> None:
    c = message.contact
    name = f"{c.first_name or ''} {c.last_name or ''}".strip()
    contact_str = f"{name} ({c.phone_number})" if name else c.phone_number
    await _save_bite_report(message, state, session, bot_instance, contact_str)


@router.message(BiteReportStates.waiting_contact, F.text & ~F.text.in_({"❌ Скасувати"}))
async def process_bite_contact_text(message: Message, state: FSMContext, session: AsyncSession, bot_instance: Bot) -> None:
    await _save_bite_report(message, state, session, bot_instance, message.text.strip())


async def _save_bite_report(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    bot_instance: Bot,
    contact: str,
) -> None:
    fsm_data = await state.get_data()
    await state.clear()

    user = await get_or_create_user(
        session=session,
        telegram_id=message.from_user.id,
        username=message.from_user.username,
    )

    report = BiteReport(
        user_id=user.id,
        bite_date=fsm_data.get("bite_date"),
        location=fsm_data.get("bite_location"),
        animal_description=fsm_data.get("animal_description"),
        vaccinated=fsm_data.get("vaccinated"),
        contact=contact,
    )
    session.add(report)
    await session.commit()

    # Повідомляємо адміна
    finder_info = f"@{message.from_user.username}" if message.from_user.username else f"ID: {message.from_user.id}"
    admin_text = (
        f"🚨 <b>Новий звіт про укус!</b>\n\n"
        f"<b>Дата укусу:</b> {fsm_data.get('bite_date', '—')}\n"
        f"<b>Місце:</b> {fsm_data.get('bite_location', '—')}\n"
        f"<b>Опис тварини:</b> {fsm_data.get('animal_description', '—')}\n"
        f"<b>Тварина щеплена:</b> {fsm_data.get('vaccinated', '—')}\n"
        f"<b>Контакт постраждалого:</b> {contact}\n"
        f"<b>Telegram:</b> {finder_info}"
    )
    for admin_id in settings.all_admin_ids:
        try:
            await bot_instance.send_message(
                chat_id=admin_id,
                text=admin_text,
                parse_mode="HTML",
            )
        except Exception as exc:
            logger.error("Failed to notify admin %s about bite: %s", admin_id, exc)

    await message.answer(
        "✅ <b>Звіт збережено!</b>\n\n"
        "Дякуємо за повідомлення. Адміністратор отримав інформацію.\n\n"
        "⚠️ <b>Нагадуємо:</b> зверніться до лікаря якомога швидше!\n"
        "📞 Екстрена допомога: <b>103</b>",
        parse_mode="HTML",
        reply_markup=smart_menu_keyboard(message.from_user.id),
    )
