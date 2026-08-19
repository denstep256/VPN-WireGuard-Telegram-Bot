import logging
import ipaddress
from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from sqlalchemy import func, select

from app.admin.admin_keyboard import cancel_kb
from app.database.models import async_session, Server
from app.addons.button_text import BUTTON_TEXTS
from config import ADMIN_ID
from app.time_utils import moscow_today

logger = logging.getLogger(__name__)


class AddServerState(StatesGroup):
    region = State()
    host_ip = State()
    port = State()
    password = State()

admin_command_add_server_router = Router()
CANCEL_HINT = f"\nДля отмены отправьте: {BUTTON_TEXTS['cancel']}"


def _admin_actor(user) -> str:
    username = user.username or "-"
    return f"{user.id} (@{username})"


def _is_admin(user_id: int) -> bool:
    return user_id == int(ADMIN_ID)


def _valid_region(region: str) -> bool:
    return (
        1 <= len(region) <= 25
        and len(region.encode("utf-8")) <= 32
        and all(character.isalnum() or character in " _-" for character in region)
    )


async def _next_region_id(session, region: str) -> int:
    current_max = await session.scalar(
        select(func.max(Server.region_id)).where(Server.region == region)
    )
    return int(current_max or 0) + 1


@admin_command_add_server_router.message(F.text == BUTTON_TEXTS["add_server"])
async def start_add_server(message: Message, state: FSMContext):
    if _is_admin(message.from_user.id):
        await message.answer(f"Введите название региона (например, Amsterdam):{CANCEL_HINT}", reply_markup=cancel_kb)
        await state.set_state(AddServerState.region)
    else:
        await message.answer('У вас нет доступа')


@admin_command_add_server_router.message(AddServerState.region)
async def process_region(message: Message, state: FSMContext):
    if _is_admin(message.from_user.id):
        region = (message.text or "").strip()
        if not _valid_region(region):
            await message.answer(
                "❌ Регион должен содержать 1-25 букв/цифр (до 32 байт UTF-8); "
                "допустимы пробел, '-' и '_'."
            )
            return
        await state.update_data(region=region)
        await message.answer(f"Введите IP-адрес сервера (например, 5.129.238.169):{CANCEL_HINT}")
        await state.set_state(AddServerState.host_ip)
    else:
        await message.answer('У вас нет доступа')


@admin_command_add_server_router.message(AddServerState.host_ip)
async def process_host_ip(message: Message, state: FSMContext):
    if _is_admin(message.from_user.id):
        ip = (message.text or "").strip()
        try:
            ipaddress.IPv4Address(ip)
        except ValueError:
            await message.answer("⚠️ Некорректный IPv4-адрес. Введите снова:")
            return
        await state.update_data(host_ip=ip)
        await message.answer(f"Введите порт (например, 51821):{CANCEL_HINT}")
        await state.set_state(AddServerState.port)
    else:
        await message.answer('У вас нет доступа')


@admin_command_add_server_router.message(AddServerState.port)
async def process_port(message: Message, state: FSMContext):
    if _is_admin(message.from_user.id):
        text = (message.text or "").strip()
        if not text.isdigit() or not (1 <= int(text) <= 65535):
            await message.answer("❌ Порт должен быть числом от 1 до 65535. Попробуйте снова:")
            return
        await state.update_data(port=text)
        await message.answer(f"Введите пароль для админки WireGuard Easy:{CANCEL_HINT}")
        await state.set_state(AddServerState.password)
    else:
        await message.answer('У вас нет доступа')


@admin_command_add_server_router.message(AddServerState.password)
async def process_password(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        await message.answer('У вас нет доступа')
        await state.clear()
        return

    password = message.text or ""
    if not password or len(password) > 256:
        await message.answer("❌ Пароль должен содержать от 1 до 256 символов.")
        return
    await state.update_data(password=password)

    # Получаем все данные
    data = await state.get_data()
    region_id: int | None = None

    # Сохраняем в БД
    try:
        async with async_session() as session:
            region_id = await _next_region_id(session, data["region"])

            new_server = Server(
                region=data['region'],
                region_id=region_id,
                host_ip=data['host_ip'],
                port=data['port'],
                password=data['password'],
                date=moscow_today().isoformat(),
                is_active=True
            )
            session.add(new_server)
            await session.commit()
    except Exception:
        logger.exception(
            "Ошибка добавления сервера: admin=%s region=%s region_id=%s host=%s:%s",
            _admin_actor(message.from_user),
            data.get("region"),
            region_id,
            data.get("host_ip"),
            data.get("port"),
        )
        await message.answer("❌ Не удалось добавить сервер из-за внутренней ошибки.")
        await state.clear()
        return

    logger.info(
        "Админ %s добавил сервер: region=%s region_id=%s host=%s:%s",
        _admin_actor(message.from_user),
        data["region"],
        region_id,
        data["host_ip"],
        data["port"],
    )
    await message.answer(
        f"✅ Сервер добавлен:\n"
        f"регион: {data['region']} №{region_id}\n"
        f"IP: {data['host_ip']}:{data['port']}"
    )
    await state.clear()
