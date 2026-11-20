from __future__ import annotations

import html
import logging
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlsplit

from aiogram.types import FSInputFile, Message

import config
from app.wg_api.wg_api import ensure_client_wg, get_client_count_wg, remove_client_wg
from app.xui_api.xui_api import XUIClient, XUIAPIError

logger = logging.getLogger(__name__)

PROTOCOL_WIREGUARD = "wireguard"
PROTOCOL_XUI = "xui"
PROTOCOL_BOTH = "both"
PROTOCOL_LABELS = {
    PROTOCOL_WIREGUARD: "WireGuard",
    PROTOCOL_XUI: "VLESS",
    PROTOCOL_BOTH: "WireGuard и VLESS",
}


@dataclass(slots=True)
class AccessResult:
    protocol: str
    client_name: str
    xui_sub_id: str | None = None
    local_file_path: Path | None = None
    subscription_url: str | None = None


def get_record_protocol(record) -> str:
    return (record.protocol or PROTOCOL_WIREGUARD).lower()


def get_protocol_label(protocol: str) -> str:
    return PROTOCOL_LABELS.get(protocol, protocol)


def has_wireguard(protocol: str) -> bool:
    return protocol in {PROTOCOL_WIREGUARD, PROTOCOL_BOTH}


def has_xui(protocol: str) -> bool:
    return protocol in {PROTOCOL_XUI, PROTOCOL_BOTH}


def format_service_location(protocol: str, region: str | None = None, region_id: int | None = None) -> str:
    if region and region_id:
        return f"{region} №{region_id}"
    return get_protocol_label(protocol)


def wg_config_path(client_name: str) -> Path:
    if Path(client_name).name != client_name or client_name in {"", ".", ".."}:
        raise ValueError("Недопустимое имя WireGuard-клиента")
    return Path(config.DIR_CONF) / f"{client_name.removesuffix('.conf')}.conf"


def wireguard_settings() -> tuple[str, str]:
    address = config.WG_ADDRESS.rstrip("/")
    if not urlsplit(address).hostname or not config.WG_API:
        raise ValueError("Заполните WG_ADDRESS и WG_API в config.py.")
    return address, config.WG_API


async def get_vpn_client_count(protocol: str) -> int:
    if protocol == PROTOCOL_WIREGUARD:
        return await get_client_count_wg(*wireguard_settings())
    async with XUIClient.connect() as panel:
        return await panel.count_clients()


async def xui_access(
    *, client_name: str, expiry_date: date | datetime | str, tg_id: int,
    username: str | None = None, xui_sub_id: str | None = None,
) -> tuple[str, str]:
    async with XUIClient.connect() as panel:
        # Resolve the public URL before changing clients so an invalid subscription
        # configuration fails before access is issued.
        base_url = await panel.subscription_base_url()
        sub_id = await panel.ensure_client(
            email=client_name, expiry=expiry_date, tg_id=tg_id, username=username, sub_id=xui_sub_id,
        )
        return sub_id, f"{base_url}/{sub_id}"


async def create_vpn_access(
    *, protocol: str, client_name: str, expiry_date: date | datetime | str,
    tg_id: int, username: str | None = None, xui_sub_id: str | None = None,
) -> AccessResult:
    access = AccessResult(protocol, client_name)
    if has_xui(protocol):
        access.xui_sub_id, access.subscription_url = await xui_access(
            client_name=client_name, expiry_date=expiry_date, tg_id=tg_id,
            username=username, xui_sub_id=xui_sub_id,
        )
    if has_wireguard(protocol):
        path = wg_config_path(client_name)
        await ensure_client_wg(client_name.removesuffix(".conf"), *wireguard_settings(), path)
        access.local_file_path = path
    return access


async def update_vpn_expiry(*, protocol: str, client_name: str, expiry_date: date | datetime | str) -> None:
    if has_xui(protocol):
        async with XUIClient.connect() as panel:
            await panel.update_expiry(client_name, expiry_date)


async def remove_vpn_access(*, protocol: str, client_name: str) -> None:
    # Both removals are attempted even when one panel is temporarily unavailable.
    errors = []
    if has_wireguard(protocol):
        try:
            await remove_client_wg(client_name.removesuffix(".conf"), *wireguard_settings())
            wg_config_path(client_name).unlink(missing_ok=True)
        except Exception as exc:
            errors.append(exc)
    if has_xui(protocol):
        try:
            async with XUIClient.connect() as panel:
                await panel.delete_client(client_name)
        except Exception as exc:
            errors.append(exc)
    if errors:
        raise ExceptionGroup("Не удалось удалить доступ VPN", errors)


async def send_access_to_user(message: Message, access: AccessResult) -> None:
    if has_wireguard(access.protocol):
        path = access.local_file_path or wg_config_path(access.client_name)
        if path.is_file():
            await message.answer_document(FSInputFile(path), caption="Конфигурация WireGuard")
        else:
            await message.answer("⚠️ Файл конфигурации WireGuard не найден. Напишите в поддержку.")
    if has_xui(access.protocol):
        if access.subscription_url:
            link = html.escape(access.subscription_url)
            await message.answer(f"🔗 <b>Ссылка подписки VLESS</b>\n<code>{link}</code>", parse_mode="HTML")
        else:
            await message.answer("⚠️ Ссылка VLESS временно недоступна. Напишите в поддержку.")


async def send_existing_access_to_user(message: Message, record) -> None:
    access = AccessResult(get_record_protocol(record), record.file_name, record.xui_sub_id)
    if has_xui(access.protocol):
        try:
            async with XUIClient.connect() as panel:
                if not access.xui_sub_id:
                    obj = await panel.get_client(record.file_name)
                    access.xui_sub_id = obj["client"].get("subId") if obj else None
                if access.xui_sub_id:
                    access.subscription_url = await panel.get_subscription_url(access.xui_sub_id)
        except XUIAPIError:
            logger.exception("Не удалось получить ссылку 3x-ui для клиента %s", record.file_name)
    await send_access_to_user(message, access)


def format_bytes(value: int) -> str:
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if abs(value) < 1024 or unit == "ТБ":
            return f"{value:.2f} {unit}"
        value /= 1024


async def build_xui_monitoring_lines(email: str) -> list[str]:
    try:
        async with XUIClient.connect() as panel:
            traffic = await panel.get_client_traffic(email)
    except XUIAPIError:
        logger.exception("Не удалось получить трафик 3x-ui для клиента %s", email)
        return ["📊 <b>Статистика VLESS временно недоступна</b>"]
    if not traffic:
        return ["📊 <b>Клиент VLESS не найден</b>"]
    up = int(traffic.get("up") or 0)
    down = int(traffic.get("down") or 0)
    total = int(traffic.get("total") or 0)
    used = format_bytes(up + down)
    quota = f"{used} / {format_bytes(total)}" if total else f"{used} (без лимита)"
    enabled = "включён" if traffic.get("enable") else "выключен"
    return [f"📊 <b>VLESS {enabled}</b>", f"Трафик <b>{quota}</b>", f"↑ {format_bytes(up)}   ↓ {format_bytes(down)}"]
