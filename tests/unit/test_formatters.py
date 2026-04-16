"""Unit-тести для bot/utils/formatters.py"""

from datetime import datetime

import pytest

from bot.models.models import Category, Request, Status, User
from bot.utils.formatters import (
    format_admin_message,
    format_channel_post,
    format_request_list_item,
    format_status_notification,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_user(telegram_id: int = 123456, username: str | None = "testuser") -> User:
    user = User()
    user.id = 1
    user.telegram_id = telegram_id
    user.username = username
    user.phone = None
    user.created_at = datetime(2024, 1, 15, 10, 30)
    return user


def make_request(
    req_id: int = 42,
    category: Category = Category.LOST,
    status: Status = Status.NEW,
    description: str = "Загублений пес біля парку",
    lat: float | None = 50.45,
    lon: float | None = 30.52,
    address_text: str | None = None,
    contact: str | None = "@volunteer",
    created_at: datetime | None = None,
) -> Request:
    req = Request()
    req.id = req_id
    req.user_id = 1
    req.category = category
    req.description = description
    req.latitude = lat
    req.longitude = lon
    req.address_text = address_text
    req.contact = contact
    req.status = status
    req.created_at = created_at or datetime(2024, 1, 15, 10, 30)
    return req


# ---------------------------------------------------------------------------
# format_admin_message
# ---------------------------------------------------------------------------

class TestFormatAdminMessage:
    def test_contains_request_id(self):
        req = make_request(req_id=99)
        user = make_user()
        result = format_admin_message(req, user)
        assert "#99" in result

    def test_contains_category(self):
        req = make_request(category=Category.INJURED)
        user = make_user()
        result = format_admin_message(req, user)
        assert "Поранена тварина" in result

    def test_contains_description(self):
        req = make_request(description="Кіт застряг на дереві")
        user = make_user()
        result = format_admin_message(req, user)
        assert "Кіт застряг на дереві" in result

    def test_contains_maps_link_when_coords(self):
        req = make_request(lat=50.45, lon=30.52)
        user = make_user()
        result = format_admin_message(req, user)
        assert "maps.google.com" in result
        assert "50.45" in result
        assert "30.52" in result

    def test_contains_address_text_when_no_coords(self):
        req = make_request(lat=None, lon=None, address_text="вул. Хрещатик, 1")
        user = make_user()
        result = format_admin_message(req, user)
        assert "вул. Хрещатик, 1" in result

    def test_location_not_specified_when_empty(self):
        req = make_request(lat=None, lon=None, address_text=None)
        user = make_user()
        result = format_admin_message(req, user)
        assert "Не вказано" in result

    def test_contains_contact(self):
        req = make_request(contact="@myhandle")
        user = make_user()
        result = format_admin_message(req, user)
        assert "@myhandle" in result

    def test_contact_not_specified_when_none(self):
        req = make_request(contact=None)
        user = make_user()
        result = format_admin_message(req, user)
        assert "Не вказано" in result

    def test_contains_datetime(self):
        req = make_request(created_at=datetime(2024, 6, 1, 14, 5))
        user = make_user()
        result = format_admin_message(req, user)
        assert "01.06.2024" in result
        assert "14:05" in result

    def test_contains_username(self):
        user = make_user(username="johndoe")
        req = make_request()
        result = format_admin_message(req, user)
        assert "@johndoe" in result

    def test_contains_telegram_id_when_no_username(self):
        user = make_user(telegram_id=987654, username=None)
        req = make_request()
        result = format_admin_message(req, user)
        assert "987654" in result

    def test_all_categories_have_labels(self):
        user = make_user()
        for cat in Category:
            req = make_request(category=cat)
            result = format_admin_message(req, user)
            assert str(cat.value) not in result or any(
                label in result for label in ["Загублена", "Поранена", "Стерилізація", "Мертва"]
            )


# ---------------------------------------------------------------------------
# format_channel_post
# ---------------------------------------------------------------------------

class TestFormatChannelPost:
    def test_contains_category(self):
        req = make_request(category=Category.LOST)
        result = format_channel_post(req)
        assert "Загублена тварина" in result

    def test_contains_description(self):
        req = make_request(description="Знайдено пораненого кота")
        result = format_channel_post(req)
        assert "Знайдено пораненого кота" in result

    def test_contains_location_with_coords(self):
        req = make_request(lat=48.5, lon=35.0)
        result = format_channel_post(req)
        assert "maps.google.com" in result

    def test_contains_location_with_address(self):
        req = make_request(lat=None, lon=None, address_text="пр. Перемоги, 10")
        result = format_channel_post(req)
        assert "пр. Перемоги, 10" in result

    def test_no_request_id_in_channel_post(self):
        req = make_request(req_id=77)
        result = format_channel_post(req)
        # Channel post should not expose internal ID
        assert "#77" not in result

    def test_injured_category_label(self):
        req = make_request(category=Category.INJURED)
        result = format_channel_post(req)
        assert "Поранена тварина" in result


# ---------------------------------------------------------------------------
# format_status_notification
# ---------------------------------------------------------------------------

class TestFormatStatusNotification:
    def test_contains_request_id(self):
        req = make_request(req_id=55)
        result = format_status_notification(req)
        assert "#55" in result

    def test_contains_new_status_in_progress(self):
        req = make_request(status=Status.IN_PROGRESS)
        result = format_status_notification(req)
        assert "В роботі" in result

    def test_contains_done_status(self):
        req = make_request(status=Status.DONE)
        result = format_status_notification(req)
        assert "Виконано" in result

    def test_contains_rejected_status(self):
        req = make_request(status=Status.REJECTED)
        result = format_status_notification(req)
        assert "Відхилено" in result

    def test_contains_new_status(self):
        req = make_request(status=Status.NEW)
        result = format_status_notification(req)
        assert "Нова" in result


# ---------------------------------------------------------------------------
# format_request_list_item
# ---------------------------------------------------------------------------

class TestFormatRequestListItem:
    def test_contains_id(self):
        req = make_request(req_id=12)
        result = format_request_list_item(req)
        assert "#12" in result

    def test_contains_category(self):
        req = make_request(category=Category.STERILIZATION)
        result = format_request_list_item(req)
        assert "Стерилізація" in result

    def test_contains_status(self):
        req = make_request(status=Status.DONE)
        result = format_request_list_item(req)
        assert "Виконано" in result

    def test_all_three_parts_present(self):
        req = make_request(req_id=7, category=Category.DEAD, status=Status.REJECTED)
        result = format_request_list_item(req)
        assert "#7" in result
        assert "Мертва тварина" in result
        assert "Відхилено" in result
