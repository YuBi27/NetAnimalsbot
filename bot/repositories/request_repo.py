from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.models import ALLOWED_TRANSITIONS, Category, Request, Status


async def create_request(
    session: AsyncSession,
    user_id: int,
    category: Category,
    description: str,
    location: dict | None,
    contact: str | None,
) -> Request:
    """Create and persist a new request with status NEW.

    location dict may contain: latitude, longitude, address_text (all optional).
    contact is a phone number or @username string.
    """
    loc = location or {}
    req = Request(
        user_id=user_id,
        category=category,
        description=description,
        latitude=loc.get("latitude"),
        longitude=loc.get("longitude"),
        address_text=loc.get("address_text"),
        status=Status.NEW,
        contact=contact,
    )
    session.add(req)
    await session.flush()
    return req


async def get_request_by_id(
    session: AsyncSession,
    request_id: int,
) -> Request | None:
    """Return a Request by its primary key, or None if not found."""
    result = await session.execute(
        select(Request).where(Request.id == request_id)
    )
    return result.scalar_one_or_none()


async def get_user_requests(
    session: AsyncSession,
    user_id: int,
) -> list[Request]:
    """Return all requests belonging to a user (by users.id FK)."""
    result = await session.execute(
        select(Request).where(Request.user_id == user_id)
    )
    return list(result.scalars().all())


async def update_status(
    session: AsyncSession,
    request_id: int,
    new_status: Status,
) -> Request:
    """Change the status of a request, validating against ALLOWED_TRANSITIONS.

    Raises ValueError if the transition is not permitted or the request is not found.
    """
    req = await get_request_by_id(session, request_id)
    if req is None:
        raise ValueError(f"Request {request_id} not found")

    allowed = ALLOWED_TRANSITIONS.get(req.status, set())
    if new_status not in allowed:
        raise ValueError(
            f"Transition {req.status} → {new_status} is not allowed. "
            f"Allowed: {allowed}"
        )

    req.status = new_status
    await session.flush()
    return req


async def get_requests_filtered(
    session: AsyncSession,
    category: Category | None = None,
    status: Status | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> list[Request]:
    """Return requests matching the given optional filters."""
    query = select(Request)

    if category is not None:
        query = query.where(Request.category == category)
    if status is not None:
        query = query.where(Request.status == status)
    if date_from is not None:
        query = query.where(Request.created_at >= date_from)
    if date_to is not None:
        query = query.where(Request.created_at <= date_to)

    result = await session.execute(query)
    return list(result.scalars().all())
