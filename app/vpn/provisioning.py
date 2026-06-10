from __future__ import annotations

import html
import logging
import os
import secrets
import string
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from aiogram.types import BufferedInputFile, FSInputFile, Message

from app.database.models import Server
from app.wg_api.wg_api import add_client_wg, get_config_wg, remove_client_wg
from app.xui_api.xui_api import (
    add_client_xui,
    get_client_count_xui,
    get_client_xui,
    get_client_traffic_xui,
    get_subscription_url_xui,
    remove_client_xui,
    update_client_expiry_xui,
)
from config import DIR_CONF

logger = logging.getLogger(__name__)

PROTOCOL_WIREGUARD = "wireguard"
PROTOCOL_XUI = "xui"
XUI_REGION = "3xUI"
XUI_REGION_ID = 1

PROTOCOL_LABELS = {
    PROTOCOL_WIREGUARD: "WireGuard",
    PROTOCOL_XUI: "3xUI",
}


@dataclass(slots=True)
class AccessResult:
    protocol: str
    client_name: str
    xui_sub_id: str | None = None
    local_file_path: str | None = None
    subscription_url: str | None = None
    links: list[str] | None = None


def normalize_protocol(protocol: str | None) -> str:
    value = (protocol or PROTOCOL_WIREGUARD).strip().lower()
    if value in {"wg", "wireguard"}:
        return PROTOCOL_WIREGUARD
    if value in {"3xui", "xui", "xray"}:
        return PROTOCOL_XUI
    return PROTOCOL_WIREGUARD


def get_record_protocol(record: Any) -> str:
    return normalize_protocol(getattr(record, "protocol", PROTOCOL_WIREGUARD))


def get_protocol_label(protocol: str | None) -> str:
    return PROTOCOL_LABELS.get(normalize_protocol(protocol), "WireGuard")


def is_xui_protocol(protocol: str | None) -> bool:
    return normalize_protocol(protocol) == PROTOCOL_XUI


def format_service_location(protocol: str | None, region: str | None = None, region_id: int | None = None) -> str:
    if is_xui_protocol(protocol):
        return "3xUI panel"
    return f"{region} №{region_id}"


def delete_local_config(client_name: str) -> bool:
    removed = False
    for path in (
        os.path.join(DIR_CONF, f"{client_name}.conf"),
        os.path.join(DIR_CONF, client_name),
    ):
        if os.path.exists(path):
            os.remove(path)
            removed = True
    return removed


def generate_xui_sub_id(length: int = 16) -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _server_url(server: Server) -> str:
    return f"https://{server.host_ip}:{server.port}"


def _require_server(server: Server | None) -> Server:
    if not server:
        raise ValueError("WireGuard server is required")
    return server


async def create_vpn_access(
    *,
    protocol: str,
    client_name: str,
    expiry_date: date | datetime | str,
    tg_id: int,
    username: str | None = None,
    server: Server | None = None,
    xui_sub_id: str | None = None,
) -> AccessResult:
    protocol = normalize_protocol(protocol)

    if protocol == PROTOCOL_WIREGUARD:
        wg_server = _require_server(server)
        await add_client_wg(client_name, _server_url(wg_server), wg_server.password)
        local_file_path = await get_config_wg(client_name, _server_url(wg_server), wg_server.password)
        return AccessResult(
            protocol=protocol,
            client_name=client_name,
            local_file_path=local_file_path or os.path.join(DIR_CONF, f"{client_name}.conf"),
        )

    sub_id = xui_sub_id or generate_xui_sub_id()
    comment = f"tg:{tg_id}"
    if username:
        comment = f"{comment} @{username}"

    await add_client_xui(
        email=client_name,
        expiry=expiry_date,
        tg_id=tg_id,
        sub_id=sub_id,
        comment=comment,
    )
    subscription_url = await _safe_xui_subscription_url(client_name, sub_id)
    return AccessResult(protocol=protocol, client_name=client_name, xui_sub_id=sub_id, subscription_url=subscription_url)


async def restore_vpn_access(
    *,
    protocol: str,
    client_name: str,
    expiry_date: date | datetime | str,
    tg_id: int,
    username: str | None = None,
    server: Server | None = None,
    xui_sub_id: str | None = None,
) -> AccessResult:
    protocol = normalize_protocol(protocol)
    if protocol == PROTOCOL_WIREGUARD:
        return await create_vpn_access(
            protocol=protocol,
            client_name=client_name,
            expiry_date=expiry_date,
            tg_id=tg_id,
            username=username,
            server=server,
        )

    sub_id = xui_sub_id or generate_xui_sub_id()
    try:
        await update_client_expiry_xui(client_name, expiry_date)
    except Exception:
        logger.info("3xUI client restore falls back to add: email=%s", client_name)
        await add_client_xui(
            email=client_name,
            expiry=expiry_date,
            tg_id=tg_id,
            sub_id=sub_id,
            comment=f"tg:{tg_id} @{username}" if username else f"tg:{tg_id}",
        )

    subscription_url = await _safe_xui_subscription_url(client_name, sub_id)
    return AccessResult(protocol=protocol, client_name=client_name, xui_sub_id=sub_id, subscription_url=subscription_url)


async def update_vpn_expiry(
    *,
    protocol: str,
    client_name: str,
    expiry_date: date | datetime | str,
) -> None:
    if not is_xui_protocol(protocol):
        return
    await update_client_expiry_xui(client_name, expiry_date)


async def remove_vpn_access(
    *,
    protocol: str,
    client_name: str,
    server: Server | None = None,
) -> tuple[bool, bool]:
    protocol = normalize_protocol(protocol)
    removed_local = False
    removed_remote = False

    if protocol == PROTOCOL_WIREGUARD:
        try:
            removed_local = delete_local_config(client_name)
        except Exception:
            logger.exception("Failed to delete local WireGuard config: client=%s", client_name)

        if server:
            await remove_client_wg(client_name, _server_url(server), server.password)
            removed_remote = True
        return removed_local, removed_remote

    await remove_client_xui(client_name)
    return False, True


async def remove_trial_access(*, trial, servers: list[Server]) -> tuple[bool, int]:
    protocol = get_record_protocol(trial)
    if protocol == PROTOCOL_XUI:
        await remove_client_xui(trial.file_name)
        return False, 1

    removed_local = delete_local_config(trial.file_name)
    removed_remote = 0
    for server in servers:
        await remove_client_wg(trial.file_name, _server_url(server), server.password)
        removed_remote += 1
    return removed_local, removed_remote


async def get_vpn_client_count(protocol: str, server: Server | None = None) -> int:
    protocol = normalize_protocol(protocol)
    if protocol == PROTOCOL_WIREGUARD:
        wg_server = _require_server(server)
        from app.wg_api.wg_api import get_client_count_wg

        return await get_client_count_wg(_server_url(wg_server), wg_server.password)
    return await get_client_count_xui()


def format_bytes(value: int | str | None) -> str:
    try:
        size = float(value or 0)
    except (TypeError, ValueError):
        return "0 B"

    units = ("B", "KB", "MB", "GB", "TB")
    idx = 0
    while size >= 1024 and idx < len(units) - 1:
        size /= 1024
        idx += 1
    if idx == 0:
        return f"{int(size)} {units[idx]}"
    return f"{size:.2f} {units[idx]}"


async def _safe_xui_subscription_url(email: str, sub_id: str | None = None) -> str | None:
    if not sub_id:
        try:
            client = await get_client_xui(email)
            sub_id = str((client or {}).get("subId") or "").strip() or None
        except Exception:
            logger.exception("Failed to fetch 3xUI client for subscription URL: email=%s", email)

    if not sub_id:
        return None

    try:
        return await get_subscription_url_xui(sub_id)
    except Exception:
        logger.exception("Failed to build 3xUI subscription URL: email=%s sub_id=%s", email, sub_id)
        return None


def build_xui_subscription_text(client_name: str, xui_sub_id: str | None, subscription_url: str | None) -> str:
    lines = [
        "🔗 <b>Доступ 3xUI</b>",
        f"Клиент: <code>{html.escape(client_name)}</code>",
    ]
    if xui_sub_id:
        lines.append(f"Sub ID: <code>{html.escape(xui_sub_id)}</code>")

    if subscription_url:
        lines.append("")
        lines.append("<b>Ссылка подписки:</b>")
        lines.append(f"<code>{html.escape(subscription_url)}</code>")
    else:
        lines.append("")
        lines.append("⚠️ Панель создала клиента, но ссылку подписки построить не удалось.")
    return "\n".join(lines)


async def send_access_to_user(message: Message, access: AccessResult) -> None:
    if access.protocol == PROTOCOL_WIREGUARD:
        file_path = access.local_file_path or os.path.join(DIR_CONF, f"{access.client_name}.conf")
        await message.answer_document(FSInputFile(file_path))
        return

    subscription_url = access.subscription_url or await _safe_xui_subscription_url(access.client_name, access.xui_sub_id)
    text = build_xui_subscription_text(access.client_name, access.xui_sub_id, subscription_url)
    if len(text) <= 3900:
        await message.answer(text, parse_mode="HTML")
        return

    raw = subscription_url or text
    await message.answer_document(
        BufferedInputFile(raw.encode("utf-8"), filename=f"{access.client_name}_3xui_subscription.txt")
    )


async def send_existing_access_to_user(message: Message, record) -> None:
    protocol = get_record_protocol(record)
    if protocol == PROTOCOL_WIREGUARD:
        file_path = os.path.join(DIR_CONF, record.file_name)
        if not file_path.endswith(".conf"):
            file_path += ".conf"
        if not os.path.exists(file_path):
            await message.answer(
                f"⚠️ Конфигурация не найдена: <code>{html.escape(os.path.basename(file_path))}</code>\n"
                f"Путь: <code>{html.escape(file_path)}</code>",
                parse_mode="HTML",
            )
            return
        await message.answer_document(FSInputFile(file_path))
        return

    subscription_url = await _safe_xui_subscription_url(record.file_name, getattr(record, "xui_sub_id", None))
    text = build_xui_subscription_text(record.file_name, getattr(record, "xui_sub_id", None), subscription_url)
    if len(text) <= 3900:
        await message.answer(text, parse_mode="HTML")
        return
    await message.answer_document(
        BufferedInputFile((subscription_url or text).encode("utf-8"), filename=f"{record.file_name}_3xui_subscription.txt")
    )


async def build_xui_monitoring_lines(email: str) -> list[str]:
    try:
        traffic = await get_client_traffic_xui(email)
    except Exception:
        logger.exception("Failed to fetch 3xUI traffic: email=%s", email)
        return ["📊 <b>3xUI мониторинг:</b> недоступен"]

    if not traffic:
        return ["📊 <b>3xUI мониторинг:</b> клиент не найден"]

    up = int(traffic.get("up") or 0)
    down = int(traffic.get("down") or 0)
    total = int(traffic.get("total") or 0)
    used = up + down
    enabled = "включён" if traffic.get("enable") else "выключен"
    quota = "без лимита" if total <= 0 else f"{format_bytes(used)} / {format_bytes(total)}"

    return [
        f"📊 <b>3xUI статус:</b> {enabled}",
        f"Трафик: <b>{quota}</b>",
        f"↑ {format_bytes(up)}   ↓ {format_bytes(down)}",
    ]
