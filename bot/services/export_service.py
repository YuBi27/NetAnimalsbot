"""Export service — produces CSV and XLSX bytes from filtered requests."""
import csv
import io
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.models import Category, Status
from bot.repositories.request_repo import get_requests_filtered

# Columns included in every export
COLUMNS = [
    "id",
    "category",
    "description",
    "status",
    "created_at",
    "latitude",
    "longitude",
    "address_text",
    "contact",
]


def _parse_filters(filters: dict | None) -> dict:
    """Convert the raw filters dict into kwargs accepted by get_requests_filtered."""
    if not filters:
        return {}

    kwargs: dict = {}

    raw_category = filters.get("category")
    if raw_category is not None:
        kwargs["category"] = Category(raw_category) if isinstance(raw_category, str) else raw_category

    raw_status = filters.get("status")
    if raw_status is not None:
        kwargs["status"] = Status(raw_status) if isinstance(raw_status, str) else raw_status

    date_from = filters.get("date_from")
    if date_from is not None:
        kwargs["date_from"] = date_from if isinstance(date_from, datetime) else datetime.fromisoformat(date_from)

    date_to = filters.get("date_to")
    if date_to is not None:
        kwargs["date_to"] = date_to if isinstance(date_to, datetime) else datetime.fromisoformat(date_to)

    return kwargs


def _row(request) -> list:
    """Extract a list of values in COLUMNS order from a Request ORM object."""
    return [
        request.id,
        request.category.value if request.category else "",
        request.description,
        request.status.value if request.status else "",
        request.created_at.isoformat() if request.created_at else "",
        request.latitude,
        request.longitude,
        request.address_text or "",
        request.contact or "",
    ]


class ExportService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def export_csv(self, filters: dict | None = None) -> bytes:
        """Return CSV-encoded bytes for all requests matching *filters*."""
        requests = await get_requests_filtered(self._session, **_parse_filters(filters))

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(COLUMNS)
        for req in requests:
            writer.writerow(_row(req))

        return buf.getvalue().encode("utf-8")

    async def export_xlsx(self, filters: dict | None = None) -> bytes:
        """Return XLSX-encoded bytes for all requests matching *filters*."""
        try:
            import openpyxl
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("openpyxl is required for XLSX export") from exc

        requests = await get_requests_filtered(self._session, **_parse_filters(filters))

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Requests"
        ws.append(COLUMNS)
        for req in requests:
            ws.append(_row(req))

        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()
