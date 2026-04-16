"""Stats service — aggregates request statistics for the admin panel."""
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.models import Category, Request, Status


@dataclass
class StatsResult:
    total: int
    by_category: dict  # {Category: int}
    by_status: dict    # {Status: int}
    today: int
    week: int
    month: int


class StatsService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_stats(self) -> StatsResult:
        """Query the database and return aggregated statistics."""
        now = datetime.utcnow()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=today_start.weekday())
        month_start = today_start.replace(day=1)

        # Total count
        total_result = await self._session.execute(select(func.count()).select_from(Request))
        total = total_result.scalar_one()

        # By category
        cat_result = await self._session.execute(
            select(Request.category, func.count()).group_by(Request.category)
        )
        by_category: dict[Category, int] = {cat: 0 for cat in Category}
        for category, count in cat_result.all():
            by_category[category] = count

        # By status
        status_result = await self._session.execute(
            select(Request.status, func.count()).group_by(Request.status)
        )
        by_status: dict[Status, int] = {s: 0 for s in Status}
        for status, count in status_result.all():
            by_status[status] = count

        # Today
        today_result = await self._session.execute(
            select(func.count()).select_from(Request).where(Request.created_at >= today_start)
        )
        today = today_result.scalar_one()

        # This week
        week_result = await self._session.execute(
            select(func.count()).select_from(Request).where(Request.created_at >= week_start)
        )
        week = week_result.scalar_one()

        # This month
        month_result = await self._session.execute(
            select(func.count()).select_from(Request).where(Request.created_at >= month_start)
        )
        month = month_result.scalar_one()

        return StatsResult(
            total=total,
            by_category=by_category,
            by_status=by_status,
            today=today,
            week=week,
            month=month,
        )
