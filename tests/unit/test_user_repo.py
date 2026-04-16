import pytest

from bot.repositories.user_repo import get_all_users, get_or_create_user, update_phone


@pytest.mark.asyncio
async def test_create_user(session):
    user = await get_or_create_user(session, telegram_id=123, username="alice")
    assert user.id is not None
    assert user.telegram_id == 123
    assert user.username == "alice"


@pytest.mark.asyncio
async def test_get_or_create_is_idempotent(session):
    """Calling twice with the same telegram_id must not create duplicates."""
    u1 = await get_or_create_user(session, telegram_id=42, username="bob")
    u2 = await get_or_create_user(session, telegram_id=42, username="bob_updated")

    assert u1.id == u2.id
    all_users = await get_all_users(session)
    assert len([u for u in all_users if u.telegram_id == 42]) == 1


@pytest.mark.asyncio
async def test_get_or_create_updates_username(session):
    await get_or_create_user(session, telegram_id=7, username="old_name")
    user = await get_or_create_user(session, telegram_id=7, username="new_name")
    assert user.username == "new_name"


@pytest.mark.asyncio
async def test_get_all_users(session):
    await get_or_create_user(session, telegram_id=1, username="u1")
    await get_or_create_user(session, telegram_id=2, username="u2")
    users = await get_all_users(session)
    assert len(users) == 2


@pytest.mark.asyncio
async def test_update_phone(session):
    await get_or_create_user(session, telegram_id=99, username="carol")
    user = await update_phone(session, telegram_id=99, phone="+380991234567")
    assert user is not None
    assert user.phone == "+380991234567"


@pytest.mark.asyncio
async def test_update_phone_nonexistent_user(session):
    result = await update_phone(session, telegram_id=9999, phone="+1")
    assert result is None
