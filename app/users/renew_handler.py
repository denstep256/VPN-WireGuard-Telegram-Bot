import os

from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery, FSInputFile, \
    BufferedInputFile
from sqlalchemy import select

import app.users.keyboard as kb
from app.addons.button_text import BUTTON_TEXTS
from app.addons.utilits import build_tariff_caption, format_tariff
from app.database.models import async_session, Subscribers, TestPeriod, Server
from app.payments.pricing import get_active_discount_percent
from app.users.handlers import texts_for_bot
from config import DIR_CONF

user_renew_router = Router()

@user_renew_router.message(F.text == BUTTON_TEXTS["my_subs"])
async def check_subscribe_button(message: Message):
    tg_id = message.from_user.id

    async with async_session() as session:
        subs_result = await session.execute(
            select(Subscribers).where(Subscribers.tg_id == tg_id)
        )
        subscribers = subs_result.scalars().all()

        test_result = await session.execute(
            select(TestPeriod).where(TestPeriod.tg_id == tg_id, TestPeriod.subscription == "trial")
        )
        test_subs = test_result.scalars().all()

    if not subscribers and not test_subs:
        await message.answer(texts_for_bot["not_active_subs"], parse_mode='HTML')
        return

    # Формируем кнопки
    buttons = []

    # Подписки из Subscribers
    for sub in subscribers:
        text = f"{sub.server_region} №{sub.server_region_id} — до {sub.expiry_date}"
        callback_data = f"renew_sub|{sub.id}"
        buttons.append([InlineKeyboardButton(text=text, callback_data=callback_data)])

    # Пробные подписки
    for test in test_subs:
        text = f"Пробная подписка активна до {test.expiry_date}"
        # Используем уникальный префикс, чтобы отличать
        callback_data = "no_renew_test"
        buttons.append([InlineKeyboardButton(text=text, callback_data=callback_data)])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer("🔐 <b>Ваши активные подключения</b>", reply_markup=keyboard, parse_mode='HTML')


@user_renew_router.callback_query(F.data == "no_renew_test")
async def handle_test_sub_click(call: CallbackQuery):
    await call.answer(
        "❌ Пробную подписку нельзя продлить.",
        show_alert=True
    )


@user_renew_router.callback_query(F.data.startswith("renew_sub|"))
async def handle_subscribe_click(call: CallbackQuery):
    tg_id = call.from_user.id
    parts = call.data.split("|")
    if len(parts) != 2 or not parts[1].isdigit():
        await call.answer("❌ Некорректные данные.", show_alert=True)
        return

    sub_id = int(parts[1])

    async with async_session() as session:
        res = await session.execute(
            select(Subscribers).where(Subscribers.id == sub_id, Subscribers.tg_id == tg_id)
        )
        sub = res.scalar_one_or_none()

    if not sub:
        await call.answer("❌ Подписка не найдена.", show_alert=True)
        return

    text = (
        "📌 <b>Ваша подписка</b>\n\n"
        f"📍 <b>Сервер:</b> {sub.server_region} №{sub.server_region_id}\n"
        f"💳 <b>Тариф:</b> {format_tariff(sub.subscription)}\n"
        f"⏳ <b>Активна до:</b> {sub.expiry_date}\n"
    )

    kb_renew = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔁 Продлить подписку", callback_data=f"renew_open|{sub_id}")]
    ])

    await call.message.answer(text, parse_mode="HTML", reply_markup=kb_renew)

    # 2) Конфиг .conf
    # Если file_name хранится без расширения — добавим .conf
    filename = sub.file_name
    if not filename.endswith(".conf"):
        filename += ".conf"

    conf_path = os.path.join(DIR_CONF, filename)

    if os.path.exists(conf_path):
        await call.message.answer_document(FSInputFile(conf_path))
    else:
        await call.message.answer(
            f"⚠️ Конфигурация не найдена: <code>{filename}</code>\n"
            f"Путь: <code>{conf_path}</code>",
            parse_mode="HTML"
        )

    await call.answer()

@user_renew_router.callback_query(F.data.startswith("renew_open|"))
async def handle_renew_open(call: CallbackQuery):
    tg_id = call.from_user.id
    parts = call.data.split("|")
    if len(parts) != 2 or not parts[1].isdigit():
        await call.answer("❌ Некорректные данные.", show_alert=True)
        return

    sub_id = int(parts[1])

    async with async_session() as session:
        # 1) достаём подписку
        res_sub = await session.execute(
            select(Subscribers).where(Subscribers.id == sub_id, Subscribers.tg_id == tg_id)
        )
        sub = res_sub.scalar_one_or_none()
        if not sub:
            await call.answer("❌ Подписка не найдена.", show_alert=True)
            return

        # 2) достаём сервер (чтобы показать в окне покупки)
        res_srv = await session.execute(
            select(Server).where(
                Server.region == sub.server_region,
                Server.region_id == sub.server_region_id,
                Server.is_active == True
            )
        )
        server = res_srv.scalar_one_or_none()

    if not server:
        await call.answer("❌ Сервер не найден или недоступен.", show_alert=True)
        return

    async with async_session() as session:
        discount_percent = await get_active_discount_percent(session, tg_id)

    caption_text = build_tariff_caption(
        server_region=server.region,
        server_region_id=server.region_id,
        discount_percent=discount_percent,
        renew_file_name=sub.file_name,
    )

    # ВАЖНО: клавиатура покупки теперь должна содержать sub_id
    buy_kb = kb.get_renew_buy_kb(sub_id=sub_id)

    with open("app/Pictures/WireGuard_ logo.jpeg", "rb") as photo_file:
        photo_bytes = photo_file.read()

    await call.message.answer_photo(
        photo=BufferedInputFile(photo_bytes, filename="wireguard.jpg"),
        caption=caption_text,
        parse_mode="HTML",
        reply_markup=buy_kb
    )
    await call.answer()
