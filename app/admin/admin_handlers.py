import asyncio
import os
import tempfile
from typing import Sequence, Iterable, Any
from datetime import datetime, date

from aiogram import Router, F
from aiogram.types import Message
from aiogram.types.input_file import FSInputFile

from sqlalchemy import select
from openpyxl import Workbook
from openpyxl.utils import get_column_letter

import app.admin.admin_keyboard as kb
from app.wg_api.wg_api import get_client_count_wg
from config import ADMIN_ID
from app.database.models import async_session, TestPeriod, User, Subscribers, Payments, Server

admin_router = Router()

DATE_FMT = "%Y-%m-%d"


def is_admin(user_id: int) -> bool:
    return user_id == int(ADMIN_ID)


def autosize_columns(ws):
    for col_idx, col in enumerate(ws.columns, start=1):
        max_len = 0
        for cell in col:
            if cell.value is None:
                continue
            max_len = max(max_len, len(str(cell.value)))
        ws.column_dimensions[get_column_letter(col_idx)].width = min(max_len + 2, 50)


def safe_parse_date(d: str) -> date | None:
    try:
        return datetime.strptime(str(d), DATE_FMT).date()
    except Exception:
        return None


async def send_excel(
    message: Message,
    filename: str,
    headers: Sequence[str],
    rows: Iterable[Sequence[Any]],
    sheet_name: str = "data",
):
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name

    ws.append(list(headers))
    for r in rows:
        ws.append(list(r))

    autosize_columns(ws)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
        tmp_path = tmp.name

    try:
        wb.save(tmp_path)
        doc = FSInputFile(tmp_path, filename=filename)
        await message.answer_document(doc)
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass


@admin_router.message(F.text == "Админ")
async def admin_panel_button(message: Message):
    if is_admin(message.from_user.id):
        await message.answer("Вы вошли в админ-панель", reply_markup=kb.admin_panel)
    else:
        await message.answer("У вас нет доступа")


@admin_router.message(F.text == "Назад (Админ)")
async def help_main_button(message: Message):
    if is_admin(message.from_user.id):
        await message.answer("Вы вернулись в главное меню", reply_markup=kb.main_admin)
    else:
        await message.answer("У вас нет доступа")


@admin_router.message(F.text == "Статистика")
async def stats_menu(message: Message):
    if is_admin(message.from_user.id):
        await message.answer("Выберите параметр, который вас интересует", reply_markup=kb.stat_kb)
    else:
        await message.answer("У вас нет доступа")


@admin_router.message(F.text == "Назад Админ")
async def back_admin(message: Message):
    if is_admin(message.from_user.id):
        await message.answer("Вы вернулись в главное меню", reply_markup=kb.admin_panel)
    else:
        await message.answer("У вас нет доступа")


@admin_router.message(F.text == "Клиенты на сервере")
async def clients_on_servers_wg(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет доступа")
        return

    async with async_session() as session:
        res = await session.execute(
            select(Server)
            .where(Server.is_active == True)
            .order_by(Server.region, Server.region_id)
        )
        servers = res.scalars().all()

    if not servers:
        await message.answer("Нет активных серверов.")
        return

    total_clients = 0
    lines = ["📊 <b>Клиенты WireGuard по серверам</b>\n"]

    for s in servers:
        url = f"http://{s.host_ip}:{s.port}"

        try:
            count = await get_client_count_wg(url, s.password)
            total_clients += int(count)
            lines.append(f"• <b>{s.region} №{s.region_id}</b>: <b>{count}</b>")
        except Exception as e:
            lines.append(f"• <b>{s.region} №{s.region_id}</b>: ⚠️ ошибка")

    lines.append(f"\n<b>Итого клиентов:</b> {total_clients}")

    await message.answer("\n".join(lines), parse_mode="HTML", reply_markup=kb.stat_kb)

# ====== Users -> Excel + summary ======
@admin_router.message(F.text == "Пользователи в боте")
async def users_excel(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет доступа")
        return

    async with async_session() as session:
        res = await session.execute(
            select(User.id, User.tg_id, User.username, User.first_name, User.date).order_by(User.id)
        )
        rows = res.all()

    total = len(rows)
    await message.answer(
        f"📊 <b>Users</b>\n"
        f"Всего пользователей: <b>{total}</b>\n"
        f"Файл: <b>users.xlsx</b>",
        parse_mode="HTML",
    )

    await send_excel(
        message=message,
        filename="users.xlsx",
        sheet_name="users",
        headers=["id", "tg_id", "username", "first_name", "date"],
        rows=rows,
    )


# ====== Subscribers -> Excel + summary ======
@admin_router.message(F.text == "Пользователи с подпиской")
async def subscribers_excel(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет доступа")
        return

    async with async_session() as session:
        res = await session.execute(
            select(
                Subscribers.id,
                Subscribers.tg_id,
                Subscribers.username,
                Subscribers.file_name,
                Subscribers.subscription,
                Subscribers.expiry_date,
                Subscribers.server_region,
                Subscribers.server_region_id,
                Subscribers.notif_oneday,
                Subscribers.note,
            ).order_by(Subscribers.id)
        )
        rows = res.all()

    today = datetime.now().date()
    total = len(rows)

    active = 0
    expired = 0
    bad_dates = 0

    by_region: dict[str, int] = {}
    for r in rows:
        # r: (id, tg_id, username, file_name, subscription, expiry_date, server_region, server_region_id, notif_oneday, note)
        exp = safe_parse_date(r[5])
        if exp is None:
            bad_dates += 1
        else:
            if exp >= today:
                active += 1
            else:
                expired += 1

        region_key = f"{r[6]} #{r[7]}"
        by_region[region_key] = by_region.get(region_key, 0) + 1

    top_regions = sorted(by_region.items(), key=lambda x: x[1], reverse=True)[:5]
    top_regions_text = "\n".join([f"• {k}: <b>{v}</b>" for k, v in top_regions]) or "—"

    await message.answer(
        f"📊 <b>Subscribers</b>\n"
        f"Всего подписок: <b>{total}</b>\n"
        f"Активных (expiry_date ≥ сегодня): <b>{active}</b>\n"
        f"Просроченных: <b>{expired}</b>\n"
        f"Некорректных дат: <b>{bad_dates}</b>\n\n"
        f"<b>Топ серверов (подписок):</b>\n{top_regions_text}\n\n"
        f"Файл: <b>subscribers.xlsx</b>",
        parse_mode="HTML",
    )

    await send_excel(
        message=message,
        filename="subscribers.xlsx",
        sheet_name="subscribers",
        headers=[
            "id", "tg_id", "username", "file_name", "subscription",
            "expiry_date", "server_region", "server_region_id",
            "notif_oneday", "note"
        ],
        rows=rows,
    )


# ====== TestPeriod -> Excel + summary ======
@admin_router.message(F.text == "Пользователи с пробным периодом")
async def testperiod_excel(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет доступа")
        return

    async with async_session() as session:
        res = await session.execute(
            select(
                TestPeriod.id,
                TestPeriod.tg_id,
                TestPeriod.username,
                TestPeriod.file_name,
                TestPeriod.subscription,
                TestPeriod.expiry_date,
                TestPeriod.notif_oneday,
            ).order_by(TestPeriod.id)
        )
        rows = res.all()

    today = datetime.now().date()
    total = len(rows)

    active = 0
    expired = 0
    bad_dates = 0

    for r in rows:
        exp = safe_parse_date(r[5])
        if exp is None:
            bad_dates += 1
        else:
            if exp >= today:
                active += 1
            else:
                expired += 1

    await message.answer(
        f"📊 <b>Test period</b>\n"
        f"Всего записей: <b>{total}</b>\n"
        f"Активных: <b>{active}</b>\n"
        f"Просроченных: <b>{expired}</b>\n"
        f"Некорректных дат: <b>{bad_dates}</b>\n\n"
        f"Файл: <b>test_period.xlsx</b>",
        parse_mode="HTML",
    )

    await send_excel(
        message=message,
        filename="test_period.xlsx",
        sheet_name="test_period",
        headers=["id", "tg_id", "username", "file_name", "subscription", "expiry_date", "notif_oneday"],
        rows=rows,
    )


# ====== Payments -> Excel + summary ======
@admin_router.message(F.text == "Платежи")
async def payments_excel(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет доступа")
        return

    async with async_session() as session:
        res = await session.execute(
            select(
                Payments.id,
                Payments.tg_id,
                Payments.username,
                Payments.price,
                Payments.date,
                Payments.tarific_plan,
                Payments.provider_payment_charge_id,
            ).order_by(Payments.id)
        )
        rows = res.all()

    total = len(rows)
    total_sum = 0.0
    count_price = 0

    by_plan: dict[str, int] = {}
    for r in rows:
        price = r[3]
        try:
            p = float(price)
            total_sum += p
            count_price += 1
        except Exception:
            pass

        plan = str(r[5])
        by_plan[plan] = by_plan.get(plan, 0) + 1

    avg = (total_sum / count_price) if count_price else 0.0

    top_plans = sorted(by_plan.items(), key=lambda x: x[1], reverse=True)[:5]
    top_plans_text = "\n".join([f"• {k}: <b>{v}</b>" for k, v in top_plans]) or "—"

    await message.answer(
        f"📊 <b>Payments</b>\n"
        f"Всего платежей: <b>{total}</b>\n"
        f"Сумма (price): <b>{total_sum:.2f}</b>\n"
        f"Средний чек: <b>{avg:.2f}</b>\n\n"
        f"<b>Топ тарифов (по кол-ву платежей):</b>\n{top_plans_text}\n\n"
        f"Файл: <b>payments.xlsx</b>",
        parse_mode="HTML",
    )

    await send_excel(
        message=message,
        filename="payments.xlsx",
        sheet_name="payments",
        headers=[
            "id", "tg_id", "username", "price", "date",
            "tarific_plan", "provider_payment_charge_id"
        ],
        rows=rows,
    )