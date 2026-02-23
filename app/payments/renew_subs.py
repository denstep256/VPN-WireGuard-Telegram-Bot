import json
from datetime import datetime, date

from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message, LabeledPrice, PreCheckoutQuery

from sqlalchemy import select, update

import config
from config import one_mounth_price, six_mounth_price, twelve_mounth_price
from app.database.models import async_session, Subscribers, Payments

from app.addons.utilits import add_months, PLAN_TO_MONTHS  # или откуда вынесешь

renew_pay_router = Router()


def plan_to_price(plan: str) -> int:
    if plan == "monthly_subs":
        return one_mounth_price
    if plan == "semi_annual_subs":
        return six_mounth_price
    if plan == "annual_subs":
        return twelve_mounth_price
    raise ValueError("Unknown plan")


def plan_to_label(plan: str) -> str:
    return {
        "monthly_subs": "Продление на 1 месяц",
        "semi_annual_subs": "Продление на 6 месяцев",
        "annual_subs": "Продление на 12 месяцев",
    }.get(plan, "Продление подписки")


def plan_to_title(plan: str) -> str:
    return {
        "monthly_subs": "Продление VPN на 1 мес.",
        "semi_annual_subs": "Продление VPN на 6 мес.",
        "annual_subs": "Продление VPN на 12 мес.",
    }.get(plan, "Продление VPN")


@renew_pay_router.callback_query(F.data.startswith("renew_pay|"))
async def create_invoice_for_renew(call: CallbackQuery):
    # renew_pay|{sub_id}|{plan}
    parts = call.data.split("|")
    if len(parts) != 3:
        await call.answer("❌ Ошибка данных.", show_alert=True)
        return

    _, sub_id_str, plan = parts
    if not sub_id_str.isdigit():
        await call.answer("❌ Некорректный ID подписки.", show_alert=True)
        return

    sub_id = int(sub_id_str)
    tg_id = call.from_user.id

    # проверим, что подписка реально принадлежит пользователю
    async with async_session() as session:
        res = await session.execute(
            select(Subscribers).where(Subscribers.id == sub_id, Subscribers.tg_id == tg_id)
        )
        sub = res.scalar_one_or_none()

    if not sub:
        await call.answer("❌ Подписка не найдена.", show_alert=True)
        return

    if plan not in PLAN_TO_MONTHS:
        await call.answer("❌ Неизвестный тариф.", show_alert=True)
        return

    price = plan_to_price(plan)
    payload = f"renew|{plan}|{sub_id}"

    # чек для провайдера (ЮKassa/CloudPayments и т.п. — в зависимости от токена)
    PROVIDER_DATA = {
        "receipt": {
            "items": [{
                "description": plan_to_label(plan),
                "quantity": "1.00",
                "amount": {"value": f"{price}.00", "currency": "RUB"},
                "vat_code": 1
            }]
        }
    }

    prices = [LabeledPrice(label=plan_to_label(plan), amount=price * 100)]

    await call.bot.send_invoice(
        chat_id=call.from_user.id,
        title=plan_to_title(plan),
        description=(
            "Оплата картой в Telegram 💳.\n"
            "В поле электронная почта укажите СВОЮ почту — на неё придёт чек."
        ),
        payload=payload,
        provider_token=config.PAYMENT_TOKEN,
        currency="RUB",
        prices=prices,
        start_parameter="renew_subscription",
        need_email=True,
        send_email_to_provider=True,
        provider_data=json.dumps(PROVIDER_DATA),
    )

    await call.answer()

@renew_pay_router.pre_checkout_query(
    F.invoice_payload.startswith("renew|")
)
async def renew_pre_checkout(pre_checkout_query: PreCheckoutQuery, bot: Bot):
    payload = pre_checkout_query.invoice_payload
    parts = payload.split("|")

    # ожидаем: renew|plan|sub_id
    if len(parts) != 3 or parts[0] != "renew":
        await bot.answer_pre_checkout_query(
            pre_checkout_query.id,
            ok=False,
            error_message="Некорректные данные платежа."
        )
        return

    _, plan, sub_id_str = parts
    if plan not in PLAN_TO_MONTHS or not sub_id_str.isdigit():
        await bot.answer_pre_checkout_query(
            pre_checkout_query.id,
            ok=False,
            error_message="Некорректные данные платежа."
        )
        return

    sub_id = int(sub_id_str)

    async with async_session() as session:
        res = await session.execute(select(Subscribers).where(Subscribers.id == sub_id))
        sub = res.scalar_one_or_none()

    if not sub:
        await bot.answer_pre_checkout_query(
            pre_checkout_query.id,
            ok=False,
            error_message="Подписка не найдена."
        )
        return

    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@renew_pay_router.message(
    F.successful_payment.invoice_payload.startswith("renew|")
)
async def handle_renew_success(message: Message):
    payload = message.successful_payment.invoice_payload
    parts = payload.split("|")

    # пропускаем НЕ renew-платежи (чтобы не конфликтовать с твоим buy-router)
    if len(parts) != 3 or parts[0] != "renew":
        return

    _, plan, sub_id_str = parts
    if plan not in PLAN_TO_MONTHS or not sub_id_str.isdigit():
        return

    sub_id = int(sub_id_str)
    tg_id = message.from_user.id
    username = message.from_user.username or "unknown"
    price = message.successful_payment.total_amount / 100
    provider_payment_charge_id = message.successful_payment.provider_payment_charge_id

    months = PLAN_TO_MONTHS[plan]
    today = date.today()

    server_region = None
    server_region_id = None
    new_expiry = None

    async with async_session() as session:
        # найдём подписку
        res = await session.execute(
            select(Subscribers).where(Subscribers.id == sub_id, Subscribers.tg_id == tg_id)
        )
        sub = res.scalar_one_or_none()
        if not sub:
            await message.answer("❌ Подписка не найдена.")
            return

        server_region = sub.server_region
        server_region_id = sub.server_region_id

        # старт продления: от текущей даты окончания, либо от сегодня если уже просрочено
        current_expiry = sub.expiry_date
        if isinstance(current_expiry, datetime):
            current_expiry = current_expiry.date()
        elif isinstance(current_expiry, str):
            try:
                current_expiry = datetime.strptime(current_expiry, "%Y-%m-%d").date()
            except (ValueError, TypeError):
                current_expiry = None

        base_date = current_expiry if current_expiry and current_expiry >= today else today
        new_expiry = add_months(base_date, months)

        # запись платежа (адаптируй поля под свою модель Payments)
        new_payment = Payments(
            tg_id=tg_id,
            username=username,
            price=price,
            date=datetime.now(),
            tarific_plan=plan,
            provider_payment_charge_id=provider_payment_charge_id,
        )
        session.add(new_payment)

        # обновим подписку
        await session.execute(
            update(Subscribers)
            .where(Subscribers.id == sub_id)
            .values(expiry_date=new_expiry)
        )
        await session.commit()

    await message.answer(
        "✅ <b>Подписка продлена!</b>\n\n"
        f"📍 <b>Сервер:</b> {server_region} №{server_region_id}\n"
        f"💳 <b>Тариф:</b> {plan}\n"
        f"⏳ <b>Активна до:</b> <b>{new_expiry}</b>",
        parse_mode="HTML"
    )