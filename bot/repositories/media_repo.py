from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.models import Media, MediaType


async def add_media(
    session: AsyncSession,
    request_id: int,
    file_id: str,
    media_type: MediaType,
) -> Media:
    """Attach a media file to a request.

    Raises ValueError if adding this file would exceed the 5-file limit (Req 2.7, 2.8).
    """
    current = await count_media(session, request_id)
    if current >= 5:
        raise ValueError(
            f"Request {request_id} already has {current} media files; limit is 5."
        )

    media = Media(request_id=request_id, file_id=file_id, type=media_type)
    session.add(media)
    await session.flush()
    return media


async def get_media_by_request(
    session: AsyncSession,
    request_id: int,
) -> list[Media]:
    """Return all media files attached to a request."""
    result = await session.execute(
        select(Media).where(Media.request_id == request_id)
    )
    return list(result.scalars().all())


async def count_media(
    session: AsyncSession,
    request_id: int,
) -> int:
    """Return the number of media files attached to a request."""
    result = await session.execute(
        select(func.count()).select_from(Media).where(Media.request_id == request_id)
    )
    return result.scalar_one()
