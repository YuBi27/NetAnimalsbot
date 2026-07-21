"""Inline-клавіатури для бота."""

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.models.models import Request, Status
from bot.utils.formatters import format_request_list_item

PAGE_SIZE = 5


def admin_request_keyboard(request_id: int, current_status: Status | None = None) -> InlineKeyboardMarkup:
    """Кнопки зміни статусу заявки — показує лише допустимі переходи."""
    from bot.models.models import ALLOWED_TRANSITIONS

    builder = InlineKeyboardBuilder()

    status_labels = {
        Status.IN_PROGRESS: "🔄 Взяти в роботу",
        Status.DONE: "✅ Закрити",
        Status.REJECTED: "❌ Відхилити",
    }
    status_keys = {
        Status.IN_PROGRESS: "in_progress",
        Status.DONE: "done",
        Status.REJECTED: "rejected",
    }

    if current_status is not None:
        allowed = ALLOWED_TRANSITIONS.get(current_status, set())
        for st in [Status.IN_PROGRESS, Status.DONE, Status.REJECTED]:
            if st in allowed:
                builder.button(
                    text=status_labels[st],
                    callback_data=f"status:{status_keys[st]}:{request_id}",
                )
    else:
        # Fallback — показуємо всі
        for st in [Status.IN_PROGRESS, Status.DONE, Status.REJECTED]:
            builder.button(
                text=status_labels[st],
                callback_data=f"status:{status_keys[st]}:{request_id}",
            )

    builder.adjust(1)
    return builder.as_markup()


def admin_requests_page_keyboard(
    requests: list[Request],
    page: int,
    total: int,
) -> InlineKeyboardMarkup:
    """Пагінація заявок для адміна — по PAGE_SIZE штук."""
    builder = InlineKeyboardBuilder()

    for req in requests:
        from bot.utils.formatters import CATEGORY_LABELS, STATUS_LABELS
        cat = CATEGORY_LABELS.get(req.category, "")
        st = STATUS_LABELS.get(req.status, "")
        builder.button(
            text=f"#{req.id} {cat} {st}",
            callback_data=f"admin_req:{req.id}",
        )

    # Навігація
    total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    nav = []
    if page > 0:
        nav.append(("◀️ Назад", f"admin_page:{page - 1}"))
    nav.append((f"{page + 1}/{total_pages}", "noop"))
    if (page + 1) * PAGE_SIZE < total:
        nav.append(("Вперед ▶️", f"admin_page:{page + 1}"))

    for text, cb in nav:
        builder.button(text=text, callback_data=cb)

    builder.adjust(1, len(nav))
    return builder.as_markup()


def user_requests_keyboard(requests: list[Request]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for request in requests:
        builder.button(
            text=format_request_list_item(request),
            callback_data=f"request:{request.id}",
        )
    builder.adjust(1)
    return builder.as_markup()


def export_format_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📄 CSV", callback_data="export:csv")
    builder.button(text="📊 XLSX", callback_data="export:xlsx")
    builder.adjust(2)
    return builder.as_markup()
