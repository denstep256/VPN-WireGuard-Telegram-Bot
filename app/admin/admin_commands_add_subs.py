import asyncio
from datetime import datetime
from dateutil.relativedelta import relativedelta  # pip install python-dateutil

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.utils.keyboard import InlineKeyboardBuilder

from sqlalchemy import select, update

from app.addons.utilits import generate_client_name, determine_subscription_type
from app.database.models import async_session, Subscribers, User, Server
from app.wg_api.wg_api import add_client_wg, get_config_wg
from config import ADMIN_ID

admin_command_add_subs_router = Router()

DATE_FMT = "%Y-%m-%d"


def is_admin(user_id: int) -> bool:
    return user_id == int(ADMIN_ID)


def parse_identifier(text: str) -> tuple[str, str]:
    raw = (text or "").strip()
    if raw.isdigit():
        return "tg_id", raw
    if raw.startswith("@"):
        raw = raw[1:]
    return "username", raw


def parse_date_str(date_str: str) -> datetime:
    return datetime.strptime(date_str, DATE_FMT)


def fmt_sub_row(s: Subscribers) -> str:
    return (
        f"• <b>id:</b> {s.id} | "
        f"<b>subscription:</b> {s.subscription} | "
        f"<b>expiry:</b> {s.expiry_date} | "
        f"<b>server:</b> {s.server_region} №{s.server_region_id}"
    )


def months_keyboard(prefix: str) -> InlineKeyboardBuilder:
    """
    prefix: callback prefix, например:
      - "manual:new_months" (для создания)
      - "manual:extend:<sub_id>" (для продления)
    """
    kb = InlineKeyboardBuilder()
    for m in (1, 3, 6, 12):
        kb.button(text=f"{m} мес.", callback_data=f"{prefix}:{m}")
    kb.button(text="❌ Отмена", callback_data="manual:cancel")
    kb.adjust(2, 2, 1)
    return kb


class ManualSubsFSM(StatesGroup):
    waiting_for_identifier = State()
    choosing_action = State()

    choosing_server = State()
    choosing_new_months = State()  # просто маркер состояния

    choosing_extend_months = State()  # маркер состояния


# ========== ENTRY ==========
@admin_command_add_subs_router.message(F.text == "Выдать подписку")
async def issue_subscription(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет доступа")
        return
    await state.clear()
    await message.answer("Введите <b>tg_id</b> или <b>username</b> пользователя (можно с @):", parse_mode="HTML")
    await state.set_state(ManualSubsFSM.waiting_for_identifier)


# ========== STEP 1: IDENTIFIER -> LIST SUBS IN ONE MESSAGE + INLINE UPDATE BUTTONS ==========
@admin_command_add_subs_router.message(ManualSubsFSM.waiting_for_identifier)
async def handle_identifier(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет доступа")
        await state.clear()
        return

    kind, value = parse_identifier(message.text)

    async with async_session() as session:
        tg_id: str | None = None

        if kind == "tg_id":
            tg_id = value
        else:
            ures = await session.execute(select(User).where(User.username == value))
            user = ures.scalar_one_or_none()
            if user:
                tg_id = str(user.tg_id)

        if not tg_id:
            await message.answer("Пользователь не найден (не удалось определить tg_id).")
            await state.clear()
            return

        await state.update_data(tg_id=tg_id)

        sres = await session.execute(
            select(Subscribers).where(Subscribers.tg_id == tg_id).order_by(Subscribers.id)
        )
        subs = sres.scalars().all()

    kb = InlineKeyboardBuilder()

    if subs:
        text = "<b>Подписки пользователя:</b>\n\n" + "\n".join(fmt_sub_row(s) for s in subs) + "\n\n"
        text += "Выберите подписку для продления или создайте новую:"
        for s in subs:
            kb.button(text=f"♻️ Продлить id {s.id}", callback_data=f"manual:pick_extend:{s.id}")
        kb.button(text="➕ Создать новую подписку", callback_data="manual:create_new")
        kb.button(text="❌ Отмена", callback_data="manual:cancel")
        kb.adjust(1)
    else:
        text = "У пользователя нет подписок.\nСоздать новую?"
        kb.button(text="➕ Создать новую подписку", callback_data="manual:create_new")
        kb.button(text="❌ Отмена", callback_data="manual:cancel")
        kb.adjust(1)

    await message.answer(text, parse_mode="HTML", reply_markup=kb.as_markup())
    await state.set_state(ManualSubsFSM.choosing_action)


# ========== ACTIONS ==========
@admin_command_add_subs_router.callback_query(ManualSubsFSM.choosing_action, F.data == "manual:create_new")
async def action_create_new(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        await state.clear()
        return
    await call.answer()
    await show_servers(call.message, state)


@admin_command_add_subs_router.callback_query(ManualSubsFSM.choosing_action, F.data.startswith("manual:pick_extend:"))
async def action_pick_extend(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        await state.clear()
        return

    try:
        sub_id = int(call.data.split(":")[-1])
    except ValueError:
        await call.answer("Некорректный id", show_alert=True)
        return

    data = await state.get_data()
    tg_id = data.get("tg_id")

    async with async_session() as session:
        res = await session.execute(
            select(Subscribers).where(Subscribers.id == sub_id, Subscribers.tg_id == tg_id)
        )
        sub = res.scalar_one_or_none()

    if not sub:
        await call.answer("Подписка не найдена", show_alert=True)
        return

    await state.update_data(sub_id=sub_id)
    kb = months_keyboard(prefix=f"manual:extend:{sub_id}")

    await call.answer()
    await call.message.answer(
        f"Подписка <b>{sub_id}</b>\n"
        f"Текущая дата окончания: <b>{sub.expiry_date}</b>\n\n"
        f"На сколько месяцев продлить?",
        parse_mode="HTML",
        reply_markup=kb.as_markup(),
    )
    await state.set_state(ManualSubsFSM.choosing_extend_months)


# ========== CREATE NEW: SHOW SERVERS ==========
async def show_servers(message: Message, state: FSMContext):
    async with async_session() as session:
        res = await session.execute(
            select(Server).where(Server.is_active == True).order_by(Server.region, Server.region_id)
        )
        servers = res.scalars().all()

    if not servers:
        await message.answer("Нет доступных активных серверов (Server.is_active=True).")
        await state.clear()
        return

    kb = InlineKeyboardBuilder()
    for s in servers:
        kb.button(
            text=f"{s.region} №{s.region_id}",
            callback_data=f"manual:server:{s.region}:{s.region_id}"
        )
    kb.button(text="❌ Отмена", callback_data="manual:cancel")
    kb.adjust(1)

    await message.answer("Выберите сервер для новой подписки:", reply_markup=kb.as_markup())
    await state.set_state(ManualSubsFSM.choosing_server)


# ========== CREATE NEW: PICK SERVER ==========
@admin_command_add_subs_router.callback_query(ManualSubsFSM.choosing_server, F.data.startswith("manual:server:"))
async def pick_server(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        await state.clear()
        return

    _, _, region, region_id_str = call.data.split(":", 3)
    try:
        region_id = int(region_id_str)
    except ValueError:
        await call.answer("Некорректный сервер", show_alert=True)
        return

    await state.update_data(server_region=region, server_region_id=region_id)
    kb = months_keyboard(prefix="manual:new_months")

    await call.answer()
    await call.message.answer("На сколько месяцев выдать подписку?", reply_markup=kb.as_markup())
    await state.set_state(ManualSubsFSM.choosing_new_months)


# ========== CREATE NEW: PICK MONTHS -> CREATE SUB + WG ==========
@admin_command_add_subs_router.callback_query(ManualSubsFSM.choosing_new_months, F.data.startswith("manual:new_months:"))
async def create_new_months(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        await state.clear()
        return

    try:
        months = int(call.data.split(":")[-1])
        if months not in (1, 3, 6, 12):
            raise ValueError
    except ValueError:
        await call.answer("Некорректный выбор", show_alert=True)
        return

    data = await state.get_data()
    tg_id = data["tg_id"]
    region = data["server_region"]
    region_id = data["server_region_id"]

    expiry_date = (datetime.now() + relativedelta(months=months)).strftime(DATE_FMT)
    subscription_type = determine_subscription_type(months * 30)  # если у вас логика "по дням"
    client_name = generate_client_name()

    async with async_session() as session:
        # username из User
        ures = await session.execute(select(User).where(User.tg_id == tg_id))
        user = ures.scalar_one_or_none()
        username = user.username if user else None

        # server
        sres = await session.execute(
            select(Server).where(
                Server.region == region,
                Server.region_id == region_id,
                Server.is_active == True
            )
        )
        server = sres.scalar_one_or_none()
        if not server:
            await call.message.answer("Сервер не найден или не активен.")
            await state.clear()
            return

        new_sub = Subscribers(
            tg_id=tg_id,
            username=username,
            file_name="check_manual",
            subscription=subscription_type,
            expiry_date=expiry_date,
            server_region=region,
            server_region_id=region_id,
            notif_oneday=False,
            note="manual_add",
        )
        session.add(new_sub)
        await session.flush()

        new_sub_id = new_sub.id

        ip = f"http://{server.host_ip}:{server.port}"
        password = server.password

        await add_client_wg(client_name, ip, password)
        await get_config_wg(client_name, ip, password)
        await asyncio.sleep(1)

        await session.execute(
            update(Subscribers).where(Subscribers.id == new_sub.id).values(file_name=client_name)
        )

        await session.commit()

    await call.answer()
    await call.message.answer(
        f"✅ Подписка создана.\n"
        f"ID: <b>{new_sub_id}</b>\n"
        f"Сервер: <b>{region} №{region_id}</b>\n"
        f"До: <b>{expiry_date}</b>\n"
        f"Файл: <b>{client_name}.conf</b>",
        parse_mode="HTML",
    )
    await state.clear()


# ========== EXTEND: PICK MONTHS -> UPDATE expiry_date ==========
@admin_command_add_subs_router.callback_query(ManualSubsFSM.choosing_extend_months, F.data.startswith("manual:extend:"))
async def extend_by_months(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        await state.clear()
        return

    parts = call.data.split(":")
    # manual:extend:<sub_id>:<months>
    if len(parts) != 4:
        await call.answer("Некорректная команда", show_alert=True)
        return

    try:
        sub_id = int(parts[2])
        months = int(parts[3])
        if months not in (1, 3, 6, 12):
            raise ValueError
    except ValueError:
        await call.answer("Некорректные данные", show_alert=True)
        return

    data = await state.get_data()
    tg_id = data.get("tg_id")

    async with async_session() as session:
        res = await session.execute(
            select(Subscribers).where(Subscribers.id == sub_id, Subscribers.tg_id == tg_id)
        )
        sub = res.scalar_one_or_none()
        if not sub:
            await call.answer("Подписка не найдена", show_alert=True)
            await state.clear()
            return

        try:
            current_exp = parse_date_str(sub.expiry_date)
        except Exception:
            await call.message.answer("У подписки некорректный формат expiry_date. Ожидается YYYY-MM-DD.")
            await state.clear()
            return

        new_exp = (current_exp + relativedelta(months=months)).strftime(DATE_FMT)

        await session.execute(
            update(Subscribers)
            .where(Subscribers.id == sub_id)
            .values(expiry_date=new_exp, note="manual_update")
        )
        await session.commit()

    await call.answer()
    await call.message.answer(
        f"✅ Подписка <b>{sub_id}</b> продлена на <b>{months}</b> мес.\n"
        f"Новая дата: <b>{new_exp}</b>",
        parse_mode="HTML",
    )
    await state.clear()


# ========== CANCEL ==========
@admin_command_add_subs_router.callback_query(F.data == "manual:cancel")
async def cancel_any(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    await state.clear()
    await call.message.answer("Ок, отменено.")
    await call.answer()
