from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery, BufferedInputFile
from sqlalchemy import select

import app.users.keyboard as kb
from app.addons.button_text import BUTTON_TEXTS
from app.addons.utilits import build_tariff_caption, format_tariff
from app.database.models import async_session, Subscribers, TestPeriod, Server
from app.payments.pricing import get_active_discount_percent
from app.users.handlers import texts_for_bot
from app.vpn.provisioning import (
    PROTOCOL_WIREGUARD,
    build_xui_monitoring_lines,
    format_service_location,
    get_protocol_label,
    get_record_protocol,
    send_existing_access_to_user,
)

user_renew_router = Router()


async def _send_trial_access(call: CallbackQuery, trial: TestPeriod) -> None:
    protocol = get_record_protocol(trial)
    text = (
        "📌 <b>Пробная подписка</b>\n\n"
        f"🛡️ <b>Протокол:</b> {get_protocol_label(protocol)}\n"
        f"⏳ <b>Активна до:</b> {trial.expiry_date}\n"
    )

    if protocol != PROTOCOL_WIREGUARD:
        monitoring_lines = await build_xui_monitoring_lines(trial.file_name)
        if monitoring_lines:
            text += "\n" + "\n".join(monitoring_lines) + "\n"

    await call.message.answer(text, parse_mode="HTML")
    await send_existing_access_to_user(call.message, trial)


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
        protocol_label = get_protocol_label(get_record_protocol(sub))
        text = f"{protocol_label}: {sub.server_region} №{sub.server_region_id} — до {sub.expiry_date}"
        callback_data = f"renew_sub|{sub.id}"
        buttons.append([InlineKeyboardButton(text=text, callback_data=callback_data)])

    # Пробные подписки
    for test in test_subs:
        protocol_label = get_protocol_label(get_record_protocol(test))
        text = f"Пробная {protocol_label} — до {test.expiry_date}"
        callback_data = f"trial_sub|{test.id}"
        buttons.append([InlineKeyboardButton(text=text, callback_data=callback_data)])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer("🔐 <b>Ваши активные подключения</b>", reply_markup=keyboard, parse_mode='HTML')


@user_renew_router.callback_query(F.data == "no_renew_test")
async def handle_test_sub_click(call: CallbackQuery):
    async with async_session() as session:
        res = await session.execute(
            select(TestPeriod).where(
                TestPeriod.tg_id == call.from_user.id,
                TestPeriod.subscription == "trial",
            )
        )
        trial = res.scalars().first()

    if not trial:
        await call.answer("❌ Пробная подписка не найдена.", show_alert=True)
        return

    await _send_trial_access(call, trial)
    await call.answer()


@user_renew_router.callback_query(F.data.startswith("trial_sub|"))
async def handle_trial_sub_click(call: CallbackQuery):
    parts = call.data.split("|")
    if len(parts) != 2 or not parts[1].isdigit():
        await call.answer("❌ Некорректные данные.", show_alert=True)
        return

    trial_id = int(parts[1])
    async with async_session() as session:
        res = await session.execute(
            select(TestPeriod).where(
                TestPeriod.id == trial_id,
                TestPeriod.tg_id == call.from_user.id,
                TestPeriod.subscription == "trial",
            )
        )
        trial = res.scalar_one_or_none()

    if not trial:
        await call.answer("❌ Пробная подписка не найдена.", show_alert=True)
        return

    await _send_trial_access(call, trial)
    await call.answer()


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

    protocol = get_record_protocol(sub)
    monitoring_lines = []
    if protocol != PROTOCOL_WIREGUARD:
        monitoring_lines = await build_xui_monitoring_lines(sub.file_name)

    text = (
        "📌 <b>Ваша подписка</b>\n\n"
        f"🛡️ <b>Протокол:</b> {get_protocol_label(protocol)}\n"
        f"📍 <b>Сервис:</b> {format_service_location(protocol, sub.server_region, sub.server_region_id)}\n"
        f"💳 <b>Тариф:</b> {format_tariff(sub.subscription)}\n"
        f"⏳ <b>Активна до:</b> {sub.expiry_date}\n"
    )
    if monitoring_lines:
        text += "\n" + "\n".join(monitoring_lines) + "\n"

    kb_renew = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔁 Продлить подписку", callback_data=f"renew_open|{sub_id}")]
    ])

    await call.message.answer(text, parse_mode="HTML", reply_markup=kb_renew)

    await send_existing_access_to_user(call.message, sub)

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

        protocol = get_record_protocol(sub)
        server = None
        if protocol == PROTOCOL_WIREGUARD:
            # 2) достаём сервер (чтобы показать в окне покупки)
            res_srv = await session.execute(
                select(Server).where(
                    Server.region == sub.server_region,
                    Server.region_id == sub.server_region_id,
                    Server.is_active == True
                )
            )
            server = res_srv.scalar_one_or_none()

    if protocol == PROTOCOL_WIREGUARD and not server:
        await call.answer("❌ Сервер не найден или недоступен.", show_alert=True)
        return

    async with async_session() as session:
        discount_percent = await get_active_discount_percent(session, tg_id)

    caption_text = build_tariff_caption(
        server_region=sub.server_region,
        server_region_id=sub.server_region_id,
        discount_percent=discount_percent,
        renew_file_name=sub.file_name,
        protocol=protocol,
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
