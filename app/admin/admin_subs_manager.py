import logging
from datetime import datetime, timedelta

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.utils.keyboard import InlineKeyboardBuilder

from sqlalchemy import select, update, delete, func

from app.addons.utilits import (
    add_months,
    delete_file_by_name,
    determine_subscription_type,
    generate_unique_client_name,
    parse_date_value,
    server_api_url,
)
from app.admin.admin_keyboard import cancel_kb
from app.database.models import async_session, Subscribers, User, Server
from app.wg_api.wg_api import provision_client_wg, remove_client_wg
from app.time_utils import moscow_today
from config import ADMIN_ID

admin_subs_router = Router()
logger = logging.getLogger(__name__)

DATE_FMT = "%Y-%m-%d"
ALLOWED_MONTHS = (1, 3, 6, 12)
PER_PAGE = 8


def is_admin(user_id: int) -> bool:
    return user_id == int(ADMIN_ID)


def _admin_actor(user) -> str:
    username = user.username or "-"
    return f"{user.id} (@{username})"


def parse_identifier(text: str) -> tuple[str, str]:
    raw = (text or "").strip()
    if raw.isdigit():
        return "tg_id", raw
    if raw.startswith("@"):
        raw = raw[1:]
    return "username", raw


def parse_date(date_str: str) -> datetime:
    return datetime.strptime(date_str, DATE_FMT)


def short_sub_button_text(s: Subscribers) -> str:
    # кнопка должна быть короткой
    # пример: "id 12 | NL#1 | 2026-02-28"
    return f"id {s.id} | {s.server_region}#{s.server_region_id} | {s.expiry_date}"


def months_kb(prefix: str) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    for m in ALLOWED_MONTHS:
        kb.button(text=f"{m} мес.", callback_data=f"{prefix}:{m}")
    kb.button(text="◀️ Назад", callback_data="subs:back_to_list")
    kb.button(text="❌ Отмена", callback_data="subs:cancel")
    kb.adjust(2, 2, 2)
    return kb


class SubsFSM(StatesGroup):
    waiting_for_identifier = State()

    listing_subs = State()
    chosen_sub = State()

    choosing_server = State()
    choosing_new_months = State()

    choosing_extend_months = State()
    waiting_reduce_days = State()

    confirming_delete = State()


# ================= ENTRY =================
@admin_subs_router.message(F.text == "Администрирование подписок")
async def start_flow(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет доступа")
        return

    await state.clear()
    await message.answer("Введите <b>tg_id</b> или <b>username</b> пользователя (можно с @):", parse_mode="HTML", reply_markup=cancel_kb)
    await state.set_state(SubsFSM.waiting_for_identifier)


# ================= RESOLVE USER + SHOW LIST =================
@admin_subs_router.message(SubsFSM.waiting_for_identifier)
async def resolve_user_and_show_list(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет доступа")
        await state.clear()
        return

    kind, value = parse_identifier(message.text)

    async with async_session() as session:
        tg_id: int | None = None

        if kind == "tg_id":
            user_result = await session.execute(
                select(User).where(User.tg_id == int(value))
            )
            user = user_result.scalar_one_or_none()
            if user:
                tg_id = int(user.tg_id)
        else:
            ures = await session.execute(
                select(User).where(func.lower(User.username) == value.lower())
            )
            user = ures.scalar_one_or_none()
            if user:
                tg_id = int(user.tg_id)

    if not tg_id:
        await message.answer("Пользователь не найден.")
        await state.clear()
        return

    await state.update_data(tg_id=tg_id, page=0)
    await show_subs_page(message, state, page=0)
    await state.set_state(SubsFSM.listing_subs)


async def fetch_subs_page(tg_id: int, page: int, per_page: int = PER_PAGE):
    offset = page * per_page
    async with async_session() as session:
        total_res = await session.execute(
            select(func.count()).select_from(Subscribers).where(Subscribers.tg_id == tg_id)
        )
        total = int(total_res.scalar() or 0)

        res = await session.execute(
            select(Subscribers)
            .where(Subscribers.tg_id == tg_id)
            .order_by(Subscribers.id)
            .limit(per_page)
            .offset(offset)
        )
        subs = res.scalars().all()

    return total, subs


async def show_subs_page(
    target: Message | CallbackQuery,
    state: FSMContext,
    page: int,
    *,
    answer_callback: bool = True,
):
    data = await state.get_data()
    tg_id = int(data["tg_id"])

    total, subs = await fetch_subs_page(tg_id, page, PER_PAGE)

    kb = InlineKeyboardBuilder()

    if total == 0:
        text = "У пользователя нет подписок."
    else:
        text = f"<b>Подписки пользователя</b> (всего: {total})\nВыберите подписку:"

        for s in subs:
            kb.button(text=short_sub_button_text(s), callback_data=f"subs:select:{s.id}")

    # пагинация
    last_page = max(0, (total - 1) // PER_PAGE) if total else 0
    nav_row = []

    if total > 0 and page > 0:
        nav_row.append(("⬅️", f"subs:page:{page-1}"))
    if total > 0 and page < last_page:
        nav_row.append(("➡️", f"subs:page:{page+1}"))

    if nav_row:
        for t, cd in nav_row:
            kb.button(text=t, callback_data=cd)

    # создание новой подписки остаётся здесь
    kb.button(text="➕ Создать новую подписку", callback_data="subs:create_new")
    kb.button(text="❌ Отмена", callback_data="subs:cancel")

    # раскладка
    if total > 0:
        # подписки по 1 в строку, потом навигация (если есть), потом create/cancel
        # kb.adjust применим грубо:
        kb.adjust(1)

    markup = kb.as_markup()

    if isinstance(target, CallbackQuery):
        await target.message.answer(text, parse_mode="HTML", reply_markup=markup)
        if answer_callback:
            await target.answer()
    else:
        await target.answer(text, parse_mode="HTML", reply_markup=markup)


@admin_subs_router.callback_query(SubsFSM.listing_subs, F.data.startswith("subs:page:"))
async def paginate(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        await state.clear()
        return

    try:
        page = int(call.data.split(":")[-1])
        if page < 0:
            raise ValueError
    except ValueError:
        await call.answer("Некорректная страница", show_alert=True)
        return

    await state.update_data(page=page)
    await show_subs_page(call, state, page=page)


# ================= SELECT SUB -> ACTION MENU =================
@admin_subs_router.callback_query(SubsFSM.listing_subs, F.data.startswith("subs:select:"))
async def select_sub(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        await state.clear()
        return

    data = await state.get_data()
    tg_id = int(data["tg_id"])

    try:
        sub_id = int(call.data.split(":")[-1])
    except ValueError:
        await call.answer("Некорректный id", show_alert=True)
        return

    async with async_session() as session:
        res = await session.execute(
            select(Subscribers).where(Subscribers.id == sub_id, Subscribers.tg_id == tg_id)
        )
        sub = res.scalar_one_or_none()

    if not sub:
        await call.answer("Подписка не найдена", show_alert=True)
        return

    await state.update_data(sub_id=sub_id)

    kb = InlineKeyboardBuilder()
    kb.button(text="♻️ Продлить", callback_data=f"subs:extend_menu:{sub_id}")
    kb.button(text="➖ Уменьшить (дни)", callback_data=f"subs:reduce_menu:{sub_id}")
    kb.button(text="🗑 Удалить", callback_data=f"subs:delete_menu:{sub_id}")
    kb.button(text="◀️ К списку", callback_data="subs:back_to_list")
    kb.button(text="❌ Отмена", callback_data="subs:cancel")
    kb.adjust(1)

    await call.message.answer(
        f"<b>Подписка id {sub.id}</b>\n"
        f"Тариф: <b>{sub.subscription}</b>\n"
        f"Сервер: <b>{sub.server_region} №{sub.server_region_id}</b>\n"
        f"До: <b>{sub.expiry_date}</b>\n"
        f"Файл: <b>{sub.file_name}</b>",
        parse_mode="HTML",
        reply_markup=kb.as_markup(),
    )
    await call.answer()
    await state.set_state(SubsFSM.chosen_sub)


@admin_subs_router.callback_query(F.data == "subs:back_to_list")
async def back_to_list(
    call: CallbackQuery,
    state: FSMContext,
    *,
    answer_callback: bool = True,
):
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        await state.clear()
        return

    data = await state.get_data()
    page = int(data.get("page", 0))
    await show_subs_page(
        call,
        state,
        page=page,
        answer_callback=answer_callback,
    )
    await state.set_state(SubsFSM.listing_subs)


# ================= CREATE NEW FLOW =================
@admin_subs_router.callback_query(SubsFSM.listing_subs, F.data == "subs:create_new")
async def create_new_start(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        await state.clear()
        return

    async with async_session() as session:
        res = await session.execute(
            select(Server).where(Server.is_active.is_(True)).order_by(Server.region, Server.region_id)
        )
        servers = res.scalars().all()

    if not servers:
        await call.message.answer("Нет активных серверов.")
        await call.answer()
        return

    kb = InlineKeyboardBuilder()
    for s in servers:
        kb.button(text=f"{s.region} №{s.region_id}", callback_data=f"subs:server:{s.id}")
    kb.button(text="◀️ К списку", callback_data="subs:back_to_list")
    kb.button(text="❌ Отмена", callback_data="subs:cancel")
    kb.adjust(1)

    await call.message.answer("Выберите сервер для новой подписки:", reply_markup=kb.as_markup())
    await call.answer()
    await state.set_state(SubsFSM.choosing_server)


@admin_subs_router.callback_query(SubsFSM.choosing_server, F.data.startswith("subs:server:"))
async def create_new_pick_server(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        await state.clear()
        return

    try:
        server_id = int(call.data.rsplit(":", 1)[-1])
    except ValueError:
        await call.answer("Некорректный сервер", show_alert=True)
        return

    async with async_session() as session:
        server = await session.get(Server, server_id)
        if not server or not server.is_active:
            await call.answer("Сервер не найден или неактивен", show_alert=True)
            return

    await state.update_data(
        server_id=server.id,
        server_region=server.region,
        server_region_id=server.region_id,
    )

    kb = months_kb(prefix="subs:new_months")
    await call.message.answer("На сколько месяцев выдать подписку?", reply_markup=kb.as_markup())
    await call.answer()
    await state.set_state(SubsFSM.choosing_new_months)


@admin_subs_router.callback_query(SubsFSM.choosing_new_months, F.data.startswith("subs:new_months:"))
async def create_new_finish(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        await state.clear()
        return

    try:
        months = int(call.data.split(":")[-1])
        if months not in ALLOWED_MONTHS:
            raise ValueError
    except ValueError:
        await call.answer("Некорректный выбор", show_alert=True)
        return

    await call.answer("Создаю подписку…")

    data = await state.get_data()
    tg_id = int(data["tg_id"])
    region = data["server_region"]
    region_id = int(data["server_region_id"])

    expiry_date = add_months(moscow_today(), months).isoformat()
    subscription_type = determine_subscription_type(months)
    client_name = None
    file_path = None
    url = None
    password = None

    try:
        async with async_session() as session:
            ures = await session.execute(select(User).where(User.tg_id == tg_id))
            user = ures.scalar_one_or_none()
            username = user.username if user else None

            server = await session.get(Server, int(data["server_id"]))
            if not server or not server.is_active:
                await call.message.answer("Сервер не найден или не активен.")
                return

            client_name = await generate_unique_client_name(session)
            url = server_api_url(server)
            password = server.password

        file_path = await provision_client_wg(client_name, url, password)

        async with async_session() as session:
            new_sub = Subscribers(
                tg_id=tg_id,
                username=username,
                file_name=client_name,
                subscription=subscription_type,
                expiry_date=expiry_date,
                server_region=region,
                server_region_id=region_id,
                notif_oneday=False,
                note="manual_add",
            )
            session.add(new_sub)
            await session.commit()
            await session.refresh(new_sub)
            new_sub_id = int(new_sub.id)
    except Exception:
        logger.exception(
            "Ошибка ручной выдачи подписки: admin=%s target_tg_id=%s region=%s region_id=%s months=%s",
            _admin_actor(call.from_user),
            tg_id,
            region,
            region_id,
            months,
        )
        if file_path and url and password:
            try:
                await remove_client_wg(client_name, url, password)
                delete_file_by_name(client_name)
            except Exception:
                logger.exception(
                    "Не удалось откатить ручную выдачу подписки: client=%s url=%s",
                    client_name,
                    url,
                )
        await call.message.answer("❌ Не удалось создать подписку из-за внутренней ошибки.")
        return

    logger.info(
        "Админ %s выдал подписку: target_tg_id=%s sub_id=%s region=%s region_id=%s months=%s expiry=%s file=%s",
        _admin_actor(call.from_user),
        tg_id,
        new_sub_id,
        region,
        region_id,
        months,
        expiry_date,
        client_name,
    )
    await call.message.answer(
        f"✅ Подписка создана.\n"
        f"ID: <b>{new_sub_id}</b>\n"
        f"Сервер: <b>{region} №{region_id}</b>\n"
        f"До: <b>{expiry_date}</b>\n"
        f"Файл: <b>{client_name}.conf</b>",
        parse_mode="HTML",
    )
    await call.message.answer_document(FSInputFile(file_path))

    # вернуться в список (обновится)
    await back_to_list(call, state, answer_callback=False)


# ================= EXTEND (MONTHS) =================
@admin_subs_router.callback_query(SubsFSM.chosen_sub, F.data.startswith("subs:extend_menu:"))
async def extend_menu(call: CallbackQuery, state: FSMContext):
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
    tg_id = int(data["tg_id"])

    async with async_session() as session:
        res = await session.execute(select(Subscribers).where(Subscribers.id == sub_id, Subscribers.tg_id == tg_id))
        sub = res.scalar_one_or_none()

    if not sub:
        await call.answer("Подписка не найдена", show_alert=True)
        return

    kb = months_kb(prefix=f"subs:extend:{sub_id}")
    await call.message.answer(
        f"Продление подписки <b>{sub_id}</b>\n"
        f"Текущая дата окончания: <b>{sub.expiry_date}</b>\n\n"
        f"На сколько месяцев продлить?",
        parse_mode="HTML",
        reply_markup=kb.as_markup(),
    )
    await call.answer()
    await state.set_state(SubsFSM.choosing_extend_months)


@admin_subs_router.callback_query(SubsFSM.choosing_extend_months, F.data.startswith("subs:extend:"))
async def extend_finish(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        await state.clear()
        return

    # subs:extend:<sub_id>:<months>
    parts = call.data.split(":")
    if len(parts) != 4:
        await call.answer("Некорректная команда", show_alert=True)
        return

    try:
        sub_id = int(parts[2])
        months = int(parts[3])
        if months not in ALLOWED_MONTHS:
            raise ValueError
    except ValueError:
        await call.answer("Некорректные данные", show_alert=True)
        return

    data = await state.get_data()
    tg_id = int(data["tg_id"])

    try:
        async with async_session() as session:
            res = await session.execute(select(Subscribers).where(Subscribers.id == sub_id, Subscribers.tg_id == tg_id))
            sub = res.scalar_one_or_none()
            if not sub:
                await call.answer("Подписка не найдена", show_alert=True)
                return

            current_exp = parse_date_value(sub.expiry_date)
            if current_exp is None:
                raise ValueError(f"Invalid subscription date: {sub.expiry_date}")
            base_date = max(current_exp, moscow_today())
            new_exp = add_months(base_date, months).isoformat()

            await session.execute(
                update(Subscribers).where(Subscribers.id == sub_id).values(expiry_date=new_exp, note="manual_update")
            )
            await session.commit()
    except Exception:
        logger.exception(
            "Ошибка продления подписки админом: admin=%s target_tg_id=%s sub_id=%s months=%s",
            _admin_actor(call.from_user),
            tg_id,
            sub_id,
            months,
        )
        await call.message.answer("❌ Не удалось продлить подписку из-за внутренней ошибки.")
        await call.answer()
        return

    logger.info(
        "Админ %s продлил подписку: target_tg_id=%s sub_id=%s months=%s new_expiry=%s",
        _admin_actor(call.from_user),
        tg_id,
        sub_id,
        months,
        new_exp,
    )
    await call.message.answer(
        f"✅ Подписка <b>{sub_id}</b> продлена на <b>{months}</b> мес.\nНовая дата: <b>{new_exp}</b>",
        parse_mode="HTML",
    )
    await back_to_list(call, state)


# ================= REDUCE (DAYS MANUAL) =================
@admin_subs_router.callback_query(SubsFSM.chosen_sub, F.data.startswith("subs:reduce_menu:"))
async def reduce_menu(call: CallbackQuery, state: FSMContext):
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
    tg_id = int(data["tg_id"])

    async with async_session() as session:
        res = await session.execute(select(Subscribers).where(Subscribers.id == sub_id, Subscribers.tg_id == tg_id))
        sub = res.scalar_one_or_none()

    if not sub:
        await call.answer("Подписка не найдена", show_alert=True)
        return

    await state.update_data(sub_id=sub_id)

    await call.message.answer(
        f"Уменьшение подписки <b>{sub_id}</b>\n"
        f"Текущая дата окончания: <b>{sub.expiry_date}</b>\n\n"
        f"Введите количество дней, которое нужно <b>убрать</b>.\n"
        f"⚠️ Если после уменьшения дата станет раньше сегодня — ввод будет отклонён (удаление делается кнопкой).",
        parse_mode="HTML",
    )
    await call.answer()
    await state.set_state(SubsFSM.waiting_reduce_days)


@admin_subs_router.message(SubsFSM.waiting_reduce_days)
async def reduce_finish(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет доступа")
        await state.clear()
        return

    try:
        days = int((message.text or "").strip())
        if days <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Введите корректное число дней (целое > 0).")
        return

    data = await state.get_data()
    tg_id = int(data["tg_id"])
    sub_id = int(data["sub_id"])

    try:
        async with async_session() as session:
            res = await session.execute(select(Subscribers).where(Subscribers.id == sub_id, Subscribers.tg_id == tg_id))
            sub = res.scalar_one_or_none()
            if not sub:
                await message.answer("Подписка не найдена.")
                await state.clear()
                return

            current_exp = parse_date(sub.expiry_date)
            new_exp_dt = current_exp - timedelta(days=days)

            # ✅ ВАШЕ ТРЕБОВАНИЕ: если дата уйдет раньше сегодня — это некорректно (не удаляем автоматом)
            if new_exp_dt.date() < moscow_today():
                await message.answer(
                    f"❌ Некорректно: после уменьшения дата станет <b>{new_exp_dt.strftime(DATE_FMT)}</b>, "
                    f"что раньше сегодняшней.\n"
                    f"Если нужно полностью убрать — используйте кнопку <b>Удалить</b>.",
                    parse_mode="HTML",
                )
                return

            new_exp = new_exp_dt.strftime(DATE_FMT)

            await session.execute(
                update(Subscribers).where(Subscribers.id == sub_id).values(expiry_date=new_exp, note="manual_reduce")
            )
            await session.commit()
    except Exception:
        logger.exception(
            "Ошибка уменьшения подписки админом: admin=%s target_tg_id=%s sub_id=%s days=%s",
            _admin_actor(message.from_user),
            tg_id,
            sub_id,
            days,
        )
        await message.answer("❌ Не удалось уменьшить подписку из-за внутренней ошибки.")
        return

    logger.info(
        "Админ %s уменьшил подписку: target_tg_id=%s sub_id=%s days=%s new_expiry=%s",
        _admin_actor(message.from_user),
        tg_id,
        sub_id,
        days,
        new_exp,
    )
    await message.answer(
        f"✅ Подписка <b>{sub_id}</b> уменьшена на <b>{days}</b> дней.\nНовая дата: <b>{new_exp}</b>",
        parse_mode="HTML",
    )
    await state.set_state(SubsFSM.listing_subs)
    page = int(data.get("page", 0))
    await show_subs_page(message, state, page=page)


# ================= DELETE (CONFIRM + REMOVE WG + REMOVE FILE + DELETE DB) =================
@admin_subs_router.callback_query(SubsFSM.chosen_sub, F.data.startswith("subs:delete_menu:"))
async def delete_menu(call: CallbackQuery, state: FSMContext):
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
    tg_id = int(data["tg_id"])

    async with async_session() as session:
        res = await session.execute(select(Subscribers).where(Subscribers.id == sub_id, Subscribers.tg_id == tg_id))
        sub = res.scalar_one_or_none()

    if not sub:
        await call.answer("Подписка не найдена", show_alert=True)
        return

    await state.update_data(sub_id=sub_id)

    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Да, удалить", callback_data=f"subs:delete_confirm:{sub_id}")
    kb.button(text="◀️ Назад", callback_data="subs:back_to_list")
    kb.button(text="❌ Отмена", callback_data="subs:cancel")
    kb.adjust(1)

    await call.message.answer(
        f"Удалить подписку <b>{sub_id}</b>?\n"
        f"Сервер: <b>{sub.server_region} №{sub.server_region_id}</b>\n"
        f"Expiry: <b>{sub.expiry_date}</b>\n"
        f"Файл: <b>{sub.file_name}</b>",
        parse_mode="HTML",
        reply_markup=kb.as_markup(),
    )
    await call.answer()
    await state.set_state(SubsFSM.confirming_delete)


@admin_subs_router.callback_query(SubsFSM.confirming_delete, F.data.startswith("subs:delete_confirm:"))
async def delete_confirm(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        await state.clear()
        return

    try:
        sub_id = int(call.data.split(":")[-1])
    except ValueError:
        await call.answer("Некорректный id", show_alert=True)
        return

    await call.answer("Удаляю подписку…")

    data = await state.get_data()
    tg_id = int(data["tg_id"])

    async with async_session() as session:
        res = await session.execute(
            select(Subscribers).where(Subscribers.id == sub_id, Subscribers.tg_id == tg_id)
        )
        sub = res.scalar_one_or_none()
        if not sub:
            await call.message.answer("Подписка не найдена")
            await state.set_state(SubsFSM.listing_subs)
            return

        client_name = sub.file_name
        region = sub.server_region
        region_id = sub.server_region_id
        srv_res = await session.execute(
            select(Server).where(
                Server.region == region,
                Server.region_id == region_id,
            )
        )
        server = srv_res.scalar_one_or_none()

    if not server:
        await call.message.answer(
            "❌ Сервер подписки не найден. Удаление остановлено, чтобы не оставить клиента в WireGuard."
        )
        return

    url = server_api_url(server)
    try:
        await remove_client_wg(client_name, url, server.password)
        removed_remote = True
    except Exception:
        logger.exception(
            "Ошибка удаления клиента на WG: sub_id=%s client=%s url=%s",
            sub_id,
            client_name,
            url,
        )
        await call.message.answer(
            "❌ WireGuard недоступен: подписка не удалена. Повторите позже."
        )
        return

    try:
        removed_local = delete_file_by_name(client_name)
        async with async_session() as session:
            await session.execute(
                delete(Subscribers).where(
                    Subscribers.id == sub_id,
                    Subscribers.tg_id == tg_id,
                )
            )
            await session.commit()
    except Exception:
        logger.exception(
            "Ошибка удаления подписки после очистки WG: admin=%s target_tg_id=%s sub_id=%s",
            _admin_actor(call.from_user),
            tg_id,
            sub_id,
        )
        await call.message.answer(
            "❌ Клиент WireGuard отключён, но запись БД удалить не удалось. Повторите операцию."
        )
        return

    msg = [f"🗑 Подписка <b>{sub_id}</b> удалена.", f"Client: <b>{client_name}</b>"]
    msg.append(f"Локальный файл: {'✅' if removed_local else 'ℹ️ не найден/не удалён'}")
    msg.append(f"Удаление на сервере WG: {'✅' if removed_remote else '⚠️ ошибка/не удалено'}")

    await call.message.answer("\n".join(msg), parse_mode="HTML")
    logger.info(
        "Админ %s удалил подписку: target_tg_id=%s sub_id=%s client=%s removed_local=%s removed_remote=%s server_region=%s server_region_id=%s",
        _admin_actor(call.from_user),
        tg_id,
        sub_id,
        client_name,
        removed_local,
        removed_remote,
        region,
        region_id,
    )

    # вернёмся к списку
    await state.set_state(SubsFSM.listing_subs)
    await back_to_list(call, state, answer_callback=False)


# ================= CANCEL =================
@admin_subs_router.callback_query(F.data == "subs:cancel")
async def cancel_any(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    await state.clear()
    await call.message.answer("Ок, отменено.")
    logger.info("Админ %s отменил действие в менеджере подписок.", _admin_actor(call.from_user))
    await call.answer()
