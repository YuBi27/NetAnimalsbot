"""Reply-клавіатури для бота.

Вимоги: 1.1, 2.2, 2.9, 2.10
"""

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import ReplyKeyboardBuilder


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(
        KeyboardButton(text="🐾 Загублена тварина — подати заявку"),
        KeyboardButton(text="🗺️ Переглянути загублених тварин"),
    )
    builder.row(
        KeyboardButton(text="🚑 Поранена або хвора тварина"),
        KeyboardButton(text="🐺 Агресивна тварина на вулиці"),
    )
    builder.row(
        KeyboardButton(text="💉 Запит на стерилізацію"),
        KeyboardButton(text="🪦 Виявлено мертву тварину"),
    )
    builder.row(
        KeyboardButton(text="🩸 Мене вкусила тварина"),
        KeyboardButton(text="🗂️ Мої заявки"),
    )
    builder.row(
        KeyboardButton(text="🔬 Стерилізую самостійно"),
        KeyboardButton(text="📖 Довідка та інформація"),
    )
    return builder.as_markup(resize_keyboard=True)


def main_menu_with_draft_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(
        KeyboardButton(text="🐾 Загублена тварина — подати заявку"),
        KeyboardButton(text="🗺️ Переглянути загублених тварин"),
    )
    builder.row(
        KeyboardButton(text="🚑 Поранена або хвора тварина"),
        KeyboardButton(text="🐺 Агресивна тварина на вулиці"),
    )
    builder.row(
        KeyboardButton(text="💉 Запит на стерилізацію"),
        KeyboardButton(text="🪦 Виявлено мертву тварину"),
    )
    builder.row(
        KeyboardButton(text="🩸 Мене вкусила тварина"),
        KeyboardButton(text="🗂️ Мої заявки"),
    )
    builder.row(
        KeyboardButton(text="🔬 Стерилізую самостійно"),
        KeyboardButton(text="📖 Довідка та інформація"),
    )
    builder.row(KeyboardButton(text="✏️ Продовжити незавершену заявку"))
    return builder.as_markup(resize_keyboard=True)


def location_keyboard() -> ReplyKeyboardMarkup:
    """Клавіатура для вибору способу надання локації.

    Вимоги: 2.2
    """
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="📍 Поділитися геолокацією", request_location=True))
    builder.row(KeyboardButton(text="Ввести адресу текстом"))
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)


def contact_keyboard() -> ReplyKeyboardMarkup:
    """Клавіатура для вибору способу надання контакту.

    Вимоги: 2.9
    """
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="📱 Поділитися контактом", request_contact=True))
    builder.row(KeyboardButton(text="Ввести @username"))
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)


def skip_media_keyboard() -> ReplyKeyboardMarkup:
    """Клавіатура з кнопкою пропуску медіа.

    Вимоги: 2.7
    """
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="⏭ Пропустити медіа"))
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)


def cancel_keyboard() -> ReplyKeyboardMarkup:
    """Клавіатура з кнопкою скасування."""
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="❌ Скасувати"))
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)


def admin_menu_keyboard() -> ReplyKeyboardMarkup:
    """Головне меню адміністратора."""
    builder = ReplyKeyboardBuilder()
    builder.row(
        KeyboardButton(text="📑 Всі заявки"),
        KeyboardButton(text="📈 Статистика"),
    )
    builder.row(
        KeyboardButton(text="💾 Експорт"),
        KeyboardButton(text="📣 Розсилка"),
    )
    builder.row(
        KeyboardButton(text="🩺 Звіти про укуси"),
        KeyboardButton(text="🏷️ Стерилізовані тварини"),
    )
    builder.row(
        KeyboardButton(text="📝 Подати заявку"),
    )
    return builder.as_markup(resize_keyboard=True)


def admin_request_submit_keyboard() -> ReplyKeyboardMarkup:
    """Меню вибору категорії заявки для адміна."""
    builder = ReplyKeyboardBuilder()
    builder.row(
        KeyboardButton(text="🐾 Загублена тварина — подати заявку"),
        KeyboardButton(text="🗺️ Переглянути загублених тварин"),
    )
    builder.row(
        KeyboardButton(text="🚑 Поранена або хвора тварина"),
        KeyboardButton(text="🐺 Агресивна тварина на вулиці"),
    )
    builder.row(
        KeyboardButton(text="💉 Запит на стерилізацію"),
        KeyboardButton(text="🪦 Виявлено мертву тварину"),
    )
    builder.row(
        KeyboardButton(text="🩸 Мене вкусила тварина"),
        KeyboardButton(text="🔬 Стерилізую самостійно"),
    )
    builder.row(
        KeyboardButton(text="🏠 Меню"),
    )
    return builder.as_markup(resize_keyboard=True)


def smart_menu_keyboard(telegram_id: int) -> ReplyKeyboardMarkup:
    """Повертає адмінське або користувацьке меню залежно від ID."""
    from bot.config import settings
    if telegram_id in settings.all_admin_ids:
        return admin_menu_keyboard()
    return main_menu_keyboard()
