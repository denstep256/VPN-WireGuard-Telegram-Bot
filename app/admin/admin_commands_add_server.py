import logging
from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from sqlalchemy import select
from datetime import datetime

from app.admin.admin_keyboard import cancel_kb
from app.database.models import async_session, Server
from app.addons.button_text import BUTTON_TEXTS
from config import ADMIN_ID

logger = logging.getLogger(__name__)


class AddServerState(StatesGroup):
    region = State()
    region_id = State()
    host_ip = State()
    port = State()
    password = State()

admin_command_add_server_router = Router()
CANCEL_HINT = f"\nДля отмены отправьте: {BUTTON_TEXTS['cancel']}"


def _admin_actor(user) -> str:
    username = user.username or "-"
    return f"{user.id} (@{username})"


@admin_command_add_server_router.message(F.text == 'Добавить сервер')
async def start_add_server(message: Message, state: FSMContext):
    if message.from_user.id == int(ADMIN_ID):
        await message.answer(f"Введите название региона (например, Amsterdam):{CANCEL_HINT}", reply_markup=cancel_kb)
        await state.set_state(AddServerState.region)
    else:
        await message.answer('У вас нет доступа')


@admin_command_add_server_router.message(AddServerState.region)
async def process_region(message: Message, state: FSMContext):
    if message.from_user.id == int(ADMIN_ID):
        await state.update_data(region=message.text.strip())
        await message.answer(f"Введите ID региона (целое число, например, 1):{CANCEL_HINT}")
        await state.set_state(AddServerState.region_id)
    else:
        await message.answer('У вас нет доступа')


@admin_command_add_server_router.message(AddServerState.region_id)
async def process_region_id(message: Message, state: FSMContext):
    if message.from_user.id == int(ADMIN_ID):
        if not message.text.isdigit():
            await message.answer("❌ ID должен быть числом. Попробуйте снова:")
            return
        await state.update_data(region_id=int(message.text))
        await message.answer(f"Введите IP-адрес сервера (например, 5.129.238.169):{CANCEL_HINT}")
        await state.set_state(AddServerState.host_ip)
    else:
        await message.answer('У вас нет доступа')


@admin_command_add_server_router.message(AddServerState.host_ip)
async def process_host_ip(message: Message, state: FSMContext):
    if message.from_user.id == int(ADMIN_ID):
        # Простая проверка IP (можно улучшить)
        ip = message.text.strip()
        if not ip.replace('.', '').replace(':', '').isdigit():
            await message.answer("⚠️ Некорректный IP. Введите снова:")
            return
        await state.update_data(host_ip=ip)
        await message.answer(f"Введите порт (например, 51821):{CANCEL_HINT}")
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
        await message.answer(f"Введите пароль для админки WireGuard Easy:{CANCEL_HINT}")
        await state.set_state(AddServerState.password)
    else:
        await message.answer('У вас нет доступа')


@admin_command_add_server_router.message(AddServerState.password)
async def process_password(message: Message, state: FSMContext):
    if message.from_user.id != int(ADMIN_ID):
        await message.answer('У вас нет доступа')
        await state.clear()
        return

    await state.update_data(password=message.text)

    # Получаем все данные
    data = await state.get_data()

    # Сохраняем в БД
    try:
        async with async_session() as session:
            # Проверка на дубликат
            existing = await session.execute(
                select(Server).where(
                    Server.region == data['region'],
                    Server.region_id == data['region_id']
                )
            )
            if existing.scalar_one_or_none():
                await message.answer("❌ Сервер с таким регионом и ID уже существует!")
                await state.clear()
                return

            new_server = Server(
                region=data['region'],
                region_id=data['region_id'],
                host_ip=data['host_ip'],
                port=data['port'],
                password=data['password'],
                date=datetime.now().strftime("%Y-%m-%d"),
                is_active=True
            )
            session.add(new_server)
            await session.commit()
    except Exception:
        logger.exception(
            "Ошибка добавления сервера: admin=%s region=%s region_id=%s host=%s:%s",
            _admin_actor(message.from_user),
            data.get("region"),
            data.get("region_id"),
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
        data["region_id"],
        data["host_ip"],
        data["port"],
    )
    await message.answer(
        f"✅ Сервер добавлен:\n"
        f"регион: {data['region']} №{data['region_id']}\n"
        f"IP: {data['host_ip']}:{data['port']}"
    )
    await state.clear()
