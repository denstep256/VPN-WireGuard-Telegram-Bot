import logging
import secrets
from datetime import date, datetime, timedelta

from sqlalchemy import select

from app.database.models import Server, Subscribers, async_session
from app.paths import config_file_path
from app.payments.pricing import format_tariff_lines
from app.settings import wg_max_clients
from app.time_utils import moscow_today
from app.wg_api.wg_api import get_client_count_wg, validate_client_name


logger = logging.getLogger(__name__)


def generate_client_name() -> str:
    # 64 bits of entropy keep collisions negligible even over long-lived installations.
    return f"ZENITH-{secrets.token_hex(8).upper()}"


def server_api_url(server: Server) -> str:
    return f"https://{str(server.host_ip).strip()}:{server.port}"


async def check_available_clients_count(region: str, region_id: int) -> bool:
    async with async_session() as session:
        result = await session.execute(
            select(Server).where(
                Server.region == region,
                Server.region_id == region_id,
                Server.is_active.is_(True),
            )
        )
        server = result.scalar_one_or_none()
        if not server:
            return False

        try:
            count = await get_client_count_wg(server_api_url(server), server.password)
        except Exception:
            logger.exception(
                "Failed to check WireGuard capacity: region=%s region_id=%s",
                region,
                region_id,
            )
            return False
        return count < wg_max_clients()


def delete_file_by_name(client_name: str) -> bool:
    normalized = validate_client_name(client_name)
    file_path = config_file_path(normalized)
    if not file_path.exists():
        return False
    file_path.unlink()
    return True


def calculate_expiry_date(payload: str, *, start: date | None = None) -> date:
    try:
        months = PLAN_TO_MONTHS[payload]
    except KeyError as exc:
        raise ValueError(f"Invalid subscription duration: {payload}") from exc
    return add_months(start or moscow_today(), months)


def determine_subscription_type(months: int) -> str:
    if months == 1:
        return "monthly_subs"
    if months == 6:
        return "semi_annual_subs"
    if months == 12:
        return "annual_subs"
    return f"manual_{months}_months"


async def get_active_subscriptions(tg_id: int):
    today = moscow_today().isoformat()
    async with async_session() as session:
        result = await session.execute(
            select(Subscribers).where(
                Subscribers.tg_id == tg_id,
                Subscribers.expiry_date >= today,
            )
        )
        return result.scalars().all()


def format_tariff(tariff_code: str) -> str:
    tariff_map = {
        "monthly_subs": "1 месяц",
        "semi_annual_subs": "6 месяцев",
        "annual_subs": "12 месяцев",
    }
    if tariff_code in tariff_map:
        return tariff_map[tariff_code]
    if tariff_code.startswith("manual_") and tariff_code.endswith("_months"):
        month_text = tariff_code.removeprefix("manual_").removesuffix("_months")
        if month_text.isdigit():
            return f"{month_text} мес. (выдано администратором)"
    return tariff_code


def parse_date_value(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.strip()
        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
    return None


def to_iso_date(value) -> str:
    parsed = parse_date_value(value)
    if parsed is None:
        raise ValueError(f"Unsupported date value: {value!r}")
    return parsed.isoformat()


def build_tariff_caption(
    server_region: str,
    server_region_id: int,
    discount_percent: int = 0,
    renew_file_name: str | None = None,
) -> str:
    lines = [
        "🛡️ <b>WireGuard VPN</b>",
        "",
        f"📍 <b>Сервер:</b> {server_region} №{server_region_id}",
    ]

    if renew_file_name:
        lines.append(f"🧾 <b>Продление для конфигурации:</b> <code>{renew_file_name}</code>")

    if discount_percent > 0:
        lines.extend(
            [
                "",
                f"🎁 <b>Промокод активирован:</b> скидка <b>{discount_percent}%</b> уже учтена в цене.",
            ]
        )

    lines.append("")
    lines.extend(format_tariff_lines(discount_percent))
    return "\n".join(lines)


def add_months(d: date, months: int) -> date:
    year = d.year + (d.month - 1 + months) // 12
    month = (d.month - 1 + months) % 12 + 1

    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    last_day = (next_month - timedelta(days=1)).day

    day = min(d.day, last_day)
    return date(year, month, day)


PLAN_TO_MONTHS = {
    "monthly_subs": 1,
    "semi_annual_subs": 6,
    "annual_subs": 12,
}
