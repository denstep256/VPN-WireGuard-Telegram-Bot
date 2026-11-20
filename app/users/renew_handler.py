import logging

from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from sqlalchemy import select

import app.users.keyboard as kb
from app.addons.button_text import BUTTON_TEXTS
from app.addons.utilits import build_tariff_caption, format_tariff
from app.database.models import async_session, Subscribers, TestPeriod
from app.payments.payments import issue_subscription
from app.payments.pricing import get_active_discount_percent
from app.users.handlers import texts_for_bot
from app.vpn.provisioning import (
    has_xui,
    build_xui_monitoring_lines,
    get_protocol_label,
    get_record_protocol,
    send_existing_access_to_user,
)

user_renew_router = Router()
logger = logging.getLogger(__name__)


async def _send_trial_access(call: CallbackQuery, trial: TestPeriod) -> None:
    protocol = get_record_protocol(trial)
    text = (
        "📌 <b>Пробная подписка</b>\n\n"
        f"🛡️ <b>Протокол:</b> {get_protocol_label(protocol)}\n"
        f"⏳ <b>Активна до:</b> {trial.expiry_date}\n"
    )

    if has_xui(protocol):
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
        text = (f"{protocol_label} — до {sub.expiry_date}" if sub.provisioned
                else f"🔑 Получить доступ · {sub.expiry_date}")
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

    if not sub.provisioned:
        await call.answer()
        try:
            result = await issue_subscription(sub.file_name, tg_id)
        except Exception:
            logger.exception("Не удалось повторить выдачу подписки %s", sub.id)
            await call.message.answer("⚠️ Выдача пока недоступна. Попробуйте позже или напишите в поддержку.")
            return
        if result is not None:
            access, _ = result
            await send_access_to_user(call.message, access)
        else:
            await call.message.answer("Доступ уже выдан. Откройте подписку ещё раз, чтобы получить настройки.")
        return

    protocol = get_record_protocol(sub)
    monitoring_lines = []
    if has_xui(protocol):
        monitoring_lines = await build_xui_monitoring_lines(sub.file_name)

    text = (
        "📌 <b>Ваша подписка</b>\n\n"
        f"🛡️ <b>Протокол:</b> {get_protocol_label(protocol)}\n"
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
            select(Subscribers).where(Subscribers.id == sub_id, Subscribers.tg_id == tg_id, Subscribers.provisioned.is_(True))
        )
        sub = res_sub.scalar_one_or_none()
        if not sub:
            await call.answer("❌ Подписка не найдена.", show_alert=True)
            return

        protocol = get_record_protocol(sub)
        discount_percent = await get_active_discount_percent(session, tg_id)

    caption_text = build_tariff_caption(
        discount_percent=discount_percent,
        renew_file_name=sub.file_name,
        protocol=protocol,
    )
    await call.message.answer(
        caption_text, parse_mode="HTML", reply_markup=kb.get_renew_buy_kb(sub_id=sub_id)
    )
    await call.answer()
