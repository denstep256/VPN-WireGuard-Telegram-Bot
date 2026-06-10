import asyncio
import logging
import platform

from aiogram import Router, F
from aiogram.types import Message
from sqlalchemy import select

import app.admin.admin_keyboard as kb
from app.admin.admin_handlers import is_admin
from app.database.models import async_session, Server
from app.users.keyboard import get_main_keyboard
from app.vpn.provisioning import PROTOCOL_WIREGUARD, server_protocol_filter

admin_pinger_router = Router()
logger = logging.getLogger(__name__)


def _admin_actor(user) -> str:
    username = user.username or "-"
    return f"{user.id} (@{username})"

async def ping_host(host: str) -> bool:
    """
    ICMP ping до хоста.
    Возвращает True если доступен.
    Работает на macOS / Linux / Windows.
    """
    system = platform.system().lower()

    if system == "windows":
        cmd = ["ping", "-n", "1", host]
    else:
        cmd = ["ping", "-c", "1", host]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )
        await proc.communicate()
        return proc.returncode == 0
    except Exception:
        logger.exception("Ошибка ping_host для host=%s", host)
        return False

@admin_pinger_router.message(F.text == "Пинг серверов")
async def ping_servers(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет доступа")
        return

    async with async_session() as session:
        res = await session.execute(
            select(Server)
            .where(Server.is_active == True, server_protocol_filter(PROTOCOL_WIREGUARD))  # noqa: E712
            .order_by(Server.region, Server.region_id)
        )
        servers = res.scalars().all()

    if not servers:
        await message.answer("Нет активных серверов.")
        return

    await message.answer(f"Проверяю {len(servers)} серверов...")

    # Параллельная проверка (быстро и безопасно)
    tasks = [ping_host(s.host_ip) for s in servers]
    results = await asyncio.gather(*tasks)

    lines = ["🩺 <b>Пинг серверов</b>\n"]

    for s, is_alive in zip(servers, results):
        if is_alive:
            lines.append(f"✅ <b>{s.region} №{s.region_id}</b> ({s.host_ip})")
        else:
            lines.append(f"❌ <b>{s.region} №{s.region_id}</b> ({s.host_ip})")

    alive_count = sum(1 for is_alive in results if is_alive)
    logger.info(
        "Админ %s выполнил пинг серверов: всего=%s доступно=%s недоступно=%s",
        _admin_actor(message.from_user),
        len(servers),
        alive_count,
        len(servers) - alive_count,
    )
    await message.answer("\n".join(lines), parse_mode="HTML", reply_markup=get_main_keyboard(message.from_user.id))
