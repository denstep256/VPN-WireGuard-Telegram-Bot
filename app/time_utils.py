from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo


MOSCOW_TZ = ZoneInfo("Europe/Moscow")


def utc_now_naive() -> datetime:
    """UTC timestamp compatible with existing naive SQLite DateTime columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def moscow_today() -> date:
    return datetime.now(MOSCOW_TZ).date()
