import logging
from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from sqlalchemy import func, select
from datetime import datetime

from app.admin.admin_keyboard import cancel_kb, admin_panel
from app.database.models import async_session, Server
from app.addons.button_text import BUTTON_TEXTS
from app.vpn.provisioning import PROTOCOL_WIREGUARD, PROTOCOL_XUI, get_protocol_label, normalize_protocol
from config import ADMIN_ID

logger = logging.getLogger(__name__)


class AddServerState(StatesGroup):
    protocol = State()
    region = State()
    host_ip = State()
    port = State()
    password = State()
    panel_base_path = State()
    inbound_ids = State()
    subscription_address = State()
    subscription_port = State()
    subscription_path = State()

admin_command_add_server_router = Router()
CANCEL_HINT = f"\nДля отмены отправьте: {BUTTON_TEXTS['cancel']}"


def _admin_actor(user) -> str:
    username = user.username or "-"
    return f"{user.id} (@{username})"


def _optional_value(value: str | None) -> str:
    value = (value or "").strip()
    return "" if value in {"", "-"} else value


def _host_prompt(protocol: str) -> str:
    if normalize_protocol(protocol) == PROTOCOL_XUI:
        return "Введите адрес панели VLESS (IP, домен или URL, например https://example.com):"
    return "Введите IP-адрес сервера (например, 5.129.238.169):"


async def _next_region_id(region: str, protocol: str) -> int:
    async with async_session() as session:
        result = await session.execute(
            select(func.max(Server.region_id)).where(
                Server.region == region,
                Server.protocol == normalize_protocol(protocol),
            )
        )
        current_max = result.scalar()
    return int(current_max or 0) + 1


async def _save_server(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    protocol = normalize_protocol(data.get("protocol"))

    try:
        async with async_session() as session:
            existing = await session.execute(
                select(Server).where(
                    Server.region == data["region"],
                    Server.region_id == data["region_id"],
                    Server.protocol == protocol,
                )
            )
            if existing.scalar_one_or_none():
                await message.answer("❌ Сервер с таким протоколом, регионом и ID уже существует!")
                await state.clear()
                return

            new_server = Server(
                region=data["region"],
                region_id=data["region_id"],
                protocol=protocol,
                host_ip=data["host_ip"],
                port=data["port"],
                password=data["password"],
                panel_base_path=data.get("panel_base_path", ""),
                inbound_ids=data.get("inbound_ids", ""),
                subscription_address=data.get("subscription_address", ""),
                subscription_port=data.get("subscription_port", ""),
                subscription_path=data.get("subscription_path", ""),
                date=datetime.now().strftime("%Y-%m-%d"),
                is_active=True,
            )
            session.add(new_server)
            await session.commit()
    except Exception:
        logger.exception(
            "Ошибка добавления сервера: admin=%s protocol=%s region=%s region_id=%s host=%s:%s",
            _admin_actor(message.from_user),
            protocol,
            data.get("region"),
            data.get("region_id"),
            data.get("host_ip"),
            data.get("port"),
        )
        await message.answer("❌ Не удалось добавить сервер из-за внутренней ошибки.")
        await state.clear()
        return

    logger.info(
        "Админ %s добавил сервер: protocol=%s region=%s region_id=%s host=%s:%s",
        _admin_actor(message.from_user),
        protocol,
        data["region"],
        data["region_id"],
        data["host_ip"],
        data["port"],
    )
    await message.answer(
        f"✅ Сервер добавлен:\n"
        f"протокол: {get_protocol_label(protocol)}\n"
        f"регион: {data['region']} №{data['region_id']}\n"
        f"адрес: {data['host_ip']}:{data['port']}",
        reply_markup=admin_panel
    )
    await state.clear()


@admin_command_add_server_router.message(F.text == 'Добавить сервер')
async def start_add_server(message: Message, state: FSMContext):
    if message.from_user.id == int(ADMIN_ID):
        await message.answer(
            f"Введите протокол сервера: WireGuard или VLESS.{CANCEL_HINT}",
            reply_markup=cancel_kb,
        )
        await state.set_state(AddServerState.protocol)
    else:
        await message.answer('У вас нет доступа')


@admin_command_add_server_router.message(AddServerState.protocol)
async def process_protocol(message: Message, state: FSMContext):
    if message.from_user.id != int(ADMIN_ID):
        await message.answer('У вас нет доступа')
        return

    raw = (message.text or "").strip().lower()
    if raw in {"wireguard", "wg"}:
        protocol = PROTOCOL_WIREGUARD
    elif raw in {"vless", "xui"}:
        protocol = PROTOCOL_XUI
    else:
        await message.answer("❌ Введите WireGuard или VLESS.")
        return

    await state.update_data(protocol=protocol)
    await message.answer(f"Введите название региона (например, Amsterdam):{CANCEL_HINT}", reply_markup=cancel_kb)
    await state.set_state(AddServerState.region)


@admin_command_add_server_router.message(AddServerState.region)
async def process_region(message: Message, state: FSMContext):
    if message.from_user.id == int(ADMIN_ID):
        region = (message.text or "").strip()
        if not region:
            await message.answer("❌ Название региона не может быть пустым. Попробуйте снова:")
            return

        data = await state.get_data()
        protocol = normalize_protocol(data.get("protocol"))
        region_id = await _next_region_id(region, protocol)
        await state.update_data(region=region, region_id=region_id)

        await message.answer(
            f"ID региона назначен автоматически: <b>{region_id}</b>\n"
            f"{_host_prompt(protocol)}{CANCEL_HINT}",
            parse_mode="HTML",
        )
        await state.set_state(AddServerState.host_ip)
    else:
        await message.answer('У вас нет доступа')


@admin_command_add_server_router.message(AddServerState.host_ip)
async def process_host_ip(message: Message, state: FSMContext):
    if message.from_user.id == int(ADMIN_ID):
        host = message.text.strip()
        data = await state.get_data()
        is_vless = normalize_protocol(data.get("protocol")) == PROTOCOL_XUI
        if not is_vless and not host.replace('.', '').replace(':', '').isdigit():
            await message.answer("⚠️ Некорректный IP. Введите снова:")
            return
        await state.update_data(host_ip=host)
        example = "6097" if is_vless else "51821"
        await message.answer(f"Введите порт (например, {example}):{CANCEL_HINT}")
        await state.set_state(AddServerState.port)
    else:
        await message.answer('У вас нет доступа')


@admin_command_add_server_router.message(AddServerState.port)
async def process_port(message: Message, state: FSMContext):
    if message.from_user.id == int(ADMIN_ID):
        if not message.text.isdigit() or not (1 <= int(message.text) <= 65535):
            await message.answer("❌ Порт должен быть числом от 1 до 65535. Попробуйте снова:")
            return
        await state.update_data(port=message.text)
        data = await state.get_data()
        if normalize_protocol(data.get("protocol")) == PROTOCOL_XUI:
            prompt = "Введите API-токен панели VLESS:"
        else:
            prompt = "Введите пароль для админки WireGuard Easy:"
        await message.answer(f"{prompt}{CANCEL_HINT}")
        await state.set_state(AddServerState.password)
    else:
        await message.answer('У вас нет доступа')


@admin_command_add_server_router.message(AddServerState.password)
async def process_password(message: Message, state: FSMContext):
    if message.from_user.id != int(ADMIN_ID):
        await message.answer('У вас нет доступа')
        await state.clear()
        return

    await state.update_data(password=message.text.strip())
    data = await state.get_data()
    if normalize_protocol(data.get("protocol")) != PROTOCOL_XUI:
        await _save_server(message, state)
        return

    await message.answer(
        f"Введите base path панели VLESS без слэшей, если есть. Если нет — отправьте -.{CANCEL_HINT}"
    )
    await state.set_state(AddServerState.panel_base_path)


@admin_command_add_server_router.message(AddServerState.panel_base_path)
async def process_panel_base_path(message: Message, state: FSMContext):
    if message.from_user.id != int(ADMIN_ID):
        await message.answer('У вас нет доступа')
        await state.clear()
        return
    await state.update_data(panel_base_path=_optional_value(message.text).strip("/"))
    await message.answer(
        f"Введите inbound IDs через запятую (например, 1,2). Если брать все подходящие inbound — отправьте -.{CANCEL_HINT}"
    )
    await state.set_state(AddServerState.inbound_ids)


@admin_command_add_server_router.message(AddServerState.inbound_ids)
async def process_inbound_ids(message: Message, state: FSMContext):
    if message.from_user.id != int(ADMIN_ID):
        await message.answer('У вас нет доступа')
        await state.clear()
        return
    inbound_ids = _optional_value(message.text)
    if inbound_ids:
        try:
            [int(item.strip()) for item in inbound_ids.split(",") if item.strip()]
        except ValueError:
            await message.answer("❌ inbound IDs должны быть числами через запятую. Попробуйте снова:")
            return
    await state.update_data(inbound_ids=inbound_ids)
    await message.answer(
        f"Введите адрес подписок, если он отличается от панели. Если нет — отправьте -.{CANCEL_HINT}"
    )
    await state.set_state(AddServerState.subscription_address)


@admin_command_add_server_router.message(AddServerState.subscription_address)
async def process_subscription_address(message: Message, state: FSMContext):
    if message.from_user.id != int(ADMIN_ID):
        await message.answer('У вас нет доступа')
        await state.clear()
        return
    await state.update_data(subscription_address=_optional_value(message.text))
    await message.answer(
        f"Введите порт подписок, если он отличается. Если нет — отправьте -.{CANCEL_HINT}"
    )
    await state.set_state(AddServerState.subscription_port)


@admin_command_add_server_router.message(AddServerState.subscription_port)
async def process_subscription_port(message: Message, state: FSMContext):
    if message.from_user.id != int(ADMIN_ID):
        await message.answer('У вас нет доступа')
        await state.clear()
        return
    subscription_port = _optional_value(message.text)
    if subscription_port and (not subscription_port.isdigit() or not (1 <= int(subscription_port) <= 65535)):
        await message.answer("❌ Порт должен быть числом от 1 до 65535 или -. Попробуйте снова:")
        return
    await state.update_data(subscription_port=subscription_port)
    await message.answer(
        f"Введите путь подписки (например, /sub), если отличается. Если нет — отправьте -.{CANCEL_HINT}"
    )
    await state.set_state(AddServerState.subscription_path)


@admin_command_add_server_router.message(AddServerState.subscription_path)
async def process_subscription_path(message: Message, state: FSMContext):
    if message.from_user.id != int(ADMIN_ID):
        await message.answer('У вас нет доступа')
        await state.clear()
        return
    await state.update_data(subscription_path=_optional_value(message.text).strip("/"))
    await _save_server(message, state)
