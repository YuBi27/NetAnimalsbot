"""Утиліти для форматування повідомлень бота."""

from bot.models.models import Category, Request, Status, User
from bot.utils.maps import format_location

# Людиночитані назви категорій
CATEGORY_LABELS: dict[Category, str] = {
    Category.LOST: "🐾 Загублена тварина",
    Category.INJURED: "🚑 Поранена або хвора тварина",
    Category.STERILIZATION: "💉 Стерилізація",
    Category.AGGRESSIVE: "🐺 Агресивна тварина",
    Category.DEAD: "🪦 Мертва тварина",
}

# Людиночитані назви статусів
STATUS_LABELS: dict[Status, str] = {
    Status.NEW: "🆕 Нова",
    Status.IN_PROGRESS: "🔄 В роботі",
    Status.AWAITING_FEEDBACK: "⏳ Очікує фідбек",
    Status.DONE: "✅ Виконано",
    Status.REJECTED: "❌ Відхилено",
}


def format_admin_message(request: Request, user: User) -> str:
    """Повне повідомлення для адміністратора з усіма деталями заявки.

    Вимоги: 3.3
    """
    category = CATEGORY_LABELS.get(request.category, request.category)
    location = format_location(request.latitude, request.longitude, request.address_text)
    username = f"@{user.username}" if user.username else f"tg://user?id={user.telegram_id}"
    contact = request.contact or "Не вказано"
    created_at = request.created_at.strftime("%d.%m.%Y %H:%M") if request.created_at else "—"

    return (
        f"📋 <b>Нова заявка #{request.id}</b>\n"
        f"\n"
        f"<b>Категорія:</b> {category}\n"
        f"<b>Опис:</b> {request.description}\n"
        f"<b>Локація:</b> {location}\n"
        f"<b>Контакт:</b> {contact}\n"
        f"<b>Дата/час:</b> {created_at}\n"
        f"<b>Користувач:</b> {username} (ID: {user.telegram_id})"
    )


def format_channel_post(request: Request) -> str:
    """Пост для публікації у Telegram-каналі.

    Вимоги: 3.5
    """
    category = CATEGORY_LABELS.get(request.category, request.category)
    location = format_location(request.latitude, request.longitude, request.address_text)

    return (
        f"{category}\n"
        f"\n"
        f"{request.description}\n"
        f"\n"
        f"📍 {location}"
    )


def format_status_notification(request: Request) -> str:
    """Сповіщення користувача про зміну статусу заявки.

    Вимоги: 4.4
    """
    status = STATUS_LABELS.get(request.status, request.status)
    return (
        f"ℹ️ Статус вашої заявки <b>#{request.id}</b> змінено:\n"
        f"{status}"
    )


def format_request_list_item(request: Request) -> str:
    """Рядок у списку заявок користувача.

    Вимоги: 5.1
    """
    category = CATEGORY_LABELS.get(request.category, request.category)
    status = STATUS_LABELS.get(request.status, request.status)
    return f"#{request.id} | {category} | {status}"
