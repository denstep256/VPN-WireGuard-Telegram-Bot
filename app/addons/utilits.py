import os
import random
from datetime import date, datetime, timedelta

from sqlalchemy import select

from app.database.models import Server, Subscribers, async_session
from app.payments.pricing import format_tariff_lines
from app.wg_api.wg_api import get_client_count_wg


generated_usernames = set()


def generate_client_name() -> str:
    while True:
        random_digits = random.randint(100000, 999999)
        client_name = f"ZENITH-{random_digits}"
        if client_name not in generated_usernames:
            generated_usernames.add(client_name)
            return client_name


async def check_available_clients_count(region: str, region_id: int) -> bool:
    async with async_session() as session:
        result = await session.execute(
            select(Server).where(
                Server.region == region,
                Server.region_id == region_id,
                Server.is_active == True,  # noqa: E712
            )
        )
        server = result.scalar_one_or_none()
        if not server:
            return False

        ip = f"https://{server.host_ip}:{server.port}"
        count = await get_client_count_wg(ip, server.password)
        return count < 60


def delete_file_by_name(client_name: str):
    file_path = f"app/auth/{client_name}.conf"
    if os.path.exists(file_path):
        os.remove(file_path)


async def calculate_expiry_date(payload: str):
    if payload == "monthly_subs":
        return (datetime.now() + timedelta(days=31)).date()
    if payload == "semi_annual_subs":
        return (datetime.now() + timedelta(days=182)).date()
    if payload == "annual_subs":
        return (datetime.now() + timedelta(days=365)).date()
    raise ValueError("Invalid subscription duration")


def determine_subscription_type(days: int) -> str:
    if days <= 31:
        return "monthly_subs"
    if days <= 183:
        return "semi_annual_subs"
    return "annual_subs"


async def get_active_subscriptions(tg_id: int):
    today = datetime.now().date().isoformat()
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
    return tariff_map.get(tariff_code, tariff_code)


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
    if parsed:
        return parsed.isoformat()
    return datetime.now().date().isoformat()


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
