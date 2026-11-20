import asyncio
import logging
import platform

from aiogram import Router, F
from aiogram.types import Message
from urllib.parse import urlsplit

import config

from app.admin.admin_handlers import is_admin
from app.users.keyboard import get_main_keyboard

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

    servers = [(label, urlsplit(url).hostname) for label, url in (
        ("WireGuard", config.WG_ADDRESS), ("3x-ui", config.XUI_PANEL_ADDRESS),
    ) if urlsplit(url).hostname]
    if not servers:
        await message.answer("Укажите адреса серверов в config.py.")
        return
    results = await asyncio.gather(*(ping_host(host) for _, host in servers))
    lines = ["🩺 <b>Пинг серверов</b>"]
    for (label, _), is_alive in zip(servers, results):
        status = "✅ отвечает" if is_alive else "❌ нет ответа"
        lines.append(f"{label} · {status}")

    logger.info("Админ %s выполнил пинг серверов: %s из %s", _admin_actor(message.from_user), sum(results), len(servers))
    await message.answer("\n".join(lines), parse_mode="HTML", reply_markup=get_main_keyboard(message.from_user.id))
