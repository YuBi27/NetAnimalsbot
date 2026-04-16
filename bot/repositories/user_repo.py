from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.models import User


async def get_or_create_user(
    session: AsyncSession,
    telegram_id: int,
    username: str | None,
) -> User:
    """Upsert user by telegram_id — idempotent, no duplicates."""
    result = await session.execute(
        select(User).where(User.telegram_id == telegram_id)
    )
    user = result.scalar_one_or_none()

    if user is None:
        user = User(telegram_id=telegram_id, username=username)
        session.add(user)
        await session.flush()
    else:
        user.username = username

    return user


async def get_all_users(session: AsyncSession) -> list[User]:
    """Return all users — used for broadcast."""
    result = await session.execute(select(User))
    return list(result.scalars().all())


async def update_phone(
    session: AsyncSession,
    telegram_id: int,
    phone: str,
) -> User | None:
    """Update phone number for a user identified by telegram_id."""
    await session.execute(
        update(User)
        .where(User.telegram_id == telegram_id)
        .values(phone=phone)
    )
    result = await session.execute(
        select(User).where(User.telegram_id == telegram_id)
    )
    return result.scalar_one_or_none()
