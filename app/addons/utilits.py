import asyncio
import html
import secrets
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import config
from sqlalchemy import select

from app.database.models import Subscribers, TestPeriod, async_session
from app.payments.pricing import format_tariff_lines
from app.vpn.provisioning import (
    PROTOCOL_BOTH, PROTOCOL_WIREGUARD, get_protocol_label, get_vpn_client_count, has_wireguard, has_xui,
)
from app.xui_api.xui_api import XUIClient


async def generate_client_name(session) -> str:
    used = set(await session.scalars(select(Subscribers.file_name).where(Subscribers.file_name.like("ZENITH-%"))))
    used.update(await session.scalars(select(TestPeriod.file_name).where(TestPeriod.file_name.like("ZENITH-%"))))
    start = secrets.randbelow(900_000)
    for offset in range(900_000):
        name = f"ZENITH-{100_000 + (start + offset) % 900_000}"
        if name not in used and f"{name}.conf" not in used:
            return name
    raise RuntimeError("Все шестизначные имена подписок заняты.")


async def _xui_has_capacity() -> bool:
    async with XUIClient.connect() as panel:
        await panel.get_target_inbound_ids()
        await panel.subscription_base_url()
        count = await panel.count_clients()
        return config.XUI_MAX_CLIENTS <= 0 or count < config.XUI_MAX_CLIENTS


async def _wireguard_has_capacity() -> bool:
    count = await get_vpn_client_count(PROTOCOL_WIREGUARD)
    return config.WG_MAX_CLIENTS <= 0 or count < config.WG_MAX_CLIENTS


async def check_available_clients_count(protocol: str = PROTOCOL_BOTH) -> bool:
    checks = []
    if has_wireguard(protocol):
        checks.append(_wireguard_has_capacity())
    if has_xui(protocol):
        checks.append(_xui_has_capacity())
    return bool(checks) and all(await asyncio.gather(*checks))


async def calculate_expiry_date(payload: str):
    if payload == "monthly_subs":
        return (datetime.now(ZoneInfo(config.VPN_TIMEZONE)) + timedelta(days=31)).date()
    if payload == "semi_annual_subs":
        return (datetime.now(ZoneInfo(config.VPN_TIMEZONE)) + timedelta(days=182)).date()
    if payload == "annual_subs":
        return (datetime.now(ZoneInfo(config.VPN_TIMEZONE)) + timedelta(days=365)).date()
    raise ValueError("Invalid subscription duration")


def determine_subscription_type(days: int) -> str:
    if days <= 31:
        return "monthly_subs"
    if days <= 183:
        return "semi_annual_subs"
    return "annual_subs"


async def get_active_subscriptions(tg_id: int):
    today = datetime.now(ZoneInfo(config.VPN_TIMEZONE)).date().isoformat()
    async with async_session() as session:
        result = await session.execute(
            select(Subscribers).where(
                Subscribers.tg_id == tg_id,
                Subscribers.expiry_date >= today,
                Subscribers.provisioned.is_(True),
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
    return datetime.now(ZoneInfo(config.VPN_TIMEZONE)).date().isoformat()


def build_tariff_caption(
    discount_percent: int = 0,
    renew_file_name: str | None = None,
    protocol: str = PROTOCOL_BOTH,
) -> str:
    lines = [f"🛡️ <b>{get_protocol_label(protocol)}</b>", ""]
    if renew_file_name:
        lines.append(f"Продление для <code>{html.escape(renew_file_name)}</code>")
    else:
        lines.extend([
            "🛡️ VLESS — гибкая настройка и хорошая маскировка трафика.",
            "⚡ WireGuard — проще в подключении и обычно быстрее.",
        ])
    if discount_percent > 0:
        lines.extend(["", f"🎁 Скидка <b>{discount_percent}%</b> уже учтена в цене."])
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
