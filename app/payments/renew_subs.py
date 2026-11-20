import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import config
from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, LabeledPrice, Message, PreCheckoutQuery
from sqlalchemy import select, text, update

from app.addons.utilits import add_months, parse_date_value
from app.database.models import Payments, Subscribers, User, async_session, refresh_user_protocol
from app.payments.pricing import (
    MIN_PAY_RUB,
    PLAN_TO_MONTHS,
    apply_discount,
    build_provider_data,
    build_renew_payload,
    calc_bonus_to_use,
    get_active_discount_percent,
    get_base_price,
    get_user_payments_count,
    mark_promo_used_if_applicable,
    parse_renew_payload,
)
from app.vpn.provisioning import (
    get_protocol_label,
    get_record_protocol,
    create_vpn_access,
    send_access_to_user,
    update_vpn_expiry,
)

renew_pay_router = Router()
logger = logging.getLogger(__name__)

RENEW_LABELS = {
    "monthly_subs": "Продление на 1 месяц",
    "semi_annual_subs": "Продление на 6 месяцев",
    "annual_subs": "Продление на 12 месяцев",
}

RENEW_TITLES = {
    "monthly_subs": "Продление VPN на 1 мес.",
    "semi_annual_subs": "Продление VPN на 6 мес.",
    "annual_subs": "Продление VPN на 12 мес.",
}


@renew_pay_router.callback_query(F.data.startswith("renew_pay|"))
async def create_invoice_for_renew(call: CallbackQuery):
    parts = (call.data or "").split("|")
    if len(parts) != 3 or not parts[1].isdigit():
        await call.answer("❌ Ошибка данных.", show_alert=True)
        return

    _, sub_id_str, plan = parts
    sub_id = int(sub_id_str)
    tg_id = call.from_user.id

    if plan not in PLAN_TO_MONTHS:
        await call.answer("❌ Неизвестный тариф.", show_alert=True)
        return

    async with async_session() as session:
        sub_res = await session.execute(
            select(Subscribers).where(Subscribers.id == sub_id, Subscribers.tg_id == tg_id, Subscribers.provisioned.is_(True))
        )
        sub = sub_res.scalar_one_or_none()
        if not sub:
            await call.answer("❌ Подписка не найдена.", show_alert=True)
            return

        discount = await get_active_discount_percent(session, tg_id)
        user_res = await session.execute(select(User).where(User.tg_id == tg_id))
        user = user_res.scalar_one_or_none()
        bonus_balance = int(getattr(user, "bonus_balance", 0) or 0) if user else 0

    base_price = get_base_price(plan)
    price_after_discount = apply_discount(base_price, discount)
    bonus_to_use = calc_bonus_to_use(price_after_discount, bonus_balance)
    final_pay_price = price_after_discount - bonus_to_use

    payload = build_renew_payload(
        plan=plan,
        sub_id=sub_id,
        discount=discount,
        bonus_used=bonus_to_use,
    )

    receipt_desc = RENEW_LABELS[plan]
    if discount > 0:
        receipt_desc = f"{receipt_desc} (скидка {discount}%)"
    provider_data = build_provider_data(receipt_desc, final_pay_price)
    prices = [LabeledPrice(label=RENEW_LABELS[plan], amount=final_pay_price * 100)]

    details: list[str] = []
    if discount > 0:
        details.append(f"✅ Применена скидка {discount}%")
    if bonus_to_use > 0:
        details.append(f"💰 Списано бонусов: {bonus_to_use} ₽")

    description = (
        "Оплата картой в Telegram 💳.\n"
        "В поле электронная почта укажите СВОЮ почту — на неё придёт чек."
    )
    if details:
        description = "\n".join(details) + "\n\n" + description

    await call.bot.send_invoice(
        chat_id=call.from_user.id,
        title=RENEW_TITLES[plan],
        description=description,
        payload=payload,
        provider_token=config.PAYMENT_TOKEN,
        currency="RUB",
        prices=prices,
        start_parameter="renew_subscription",
        need_email=True,
        send_email_to_provider=True,
        provider_data=json.dumps(provider_data),
    )

    await call.answer()


@renew_pay_router.pre_checkout_query(F.invoice_payload.startswith("renew|"))
async def renew_pre_checkout(pre_checkout_query: PreCheckoutQuery, bot: Bot):
    try:
        plan, sub_id, _, _ = parse_renew_payload(pre_checkout_query.invoice_payload)
    except ValueError:
        await bot.answer_pre_checkout_query(
            pre_checkout_query.id,
            ok=False,
            error_message="Некорректные данные платежа.",
        )
        return

    if plan not in PLAN_TO_MONTHS:
        await bot.answer_pre_checkout_query(
            pre_checkout_query.id,
            ok=False,
            error_message="Некорректные данные платежа.",
        )
        return

    async with async_session() as session:
        res = await session.execute(
            select(Subscribers).where(
                Subscribers.id == sub_id,
                Subscribers.tg_id == pre_checkout_query.from_user.id,
                Subscribers.provisioned.is_(True),
            )
        )
        sub = res.scalar_one_or_none()

    if not sub:
        await bot.answer_pre_checkout_query(
            pre_checkout_query.id,
            ok=False,
            error_message="Подписка не найдена.",
        )
        return

    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)


@renew_pay_router.message(F.successful_payment.invoice_payload.startswith("renew|"))
async def handle_renew_success(message: Message):
    try:
        plan, sub_id, discount_from_payload, bonus_reserved = parse_renew_payload(
            message.successful_payment.invoice_payload
        )
    except ValueError:
        logger.error(
            "Некорректный payload продления: tg_id=%s payload=%s",
            message.from_user.id if message.from_user else None,
            message.successful_payment.invoice_payload,
        )
        return

    if plan not in PLAN_TO_MONTHS:
        logger.error(
            "Неизвестный тариф в payload продления: tg_id=%s plan=%s payload=%s",
            message.from_user.id if message.from_user else None,
            plan,
            message.successful_payment.invoice_payload,
        )
        return

    tg_id = message.from_user.id
    username = message.from_user.username or "unknown"
    paid_rub = int(message.successful_payment.total_amount / 100)
    provider_payment_charge_id = message.successful_payment.provider_payment_charge_id

    months = PLAN_TO_MONTHS[plan]
    today = datetime.now(ZoneInfo(config.VPN_TIMEZONE)).date()

    async with async_session() as session:
        await session.execute(text("BEGIN IMMEDIATE"))
        already_paid = await session.scalar(select(Payments.id).where(
            Payments.provider_payment_charge_id == provider_payment_charge_id,
        ).limit(1))
        if already_paid is not None:
            return

        prev_payments_count = await get_user_payments_count(session, tg_id)
        is_first_payment = prev_payments_count == 0

        user_res = await session.execute(select(User).where(User.tg_id == tg_id))
        user = user_res.scalar_one_or_none()
        if not user:
            logger.error(
                "Пользователь не найден при продлении: tg_id=%s sub_id=%s plan=%s payment_charge_id=%s",
                tg_id,
                sub_id,
                plan,
                provider_payment_charge_id,
            )
            await message.answer("❌ Пользователь не найден.")
            return

        sub_res = await session.execute(
            select(Subscribers).where(Subscribers.id == sub_id, Subscribers.tg_id == tg_id, Subscribers.provisioned.is_(True))
        )
        sub = sub_res.scalar_one_or_none()
        if not sub:
            logger.error(
                "Подписка не найдена при продлении: tg_id=%s sub_id=%s plan=%s payment_charge_id=%s",
                tg_id,
                sub_id,
                plan,
                provider_payment_charge_id,
            )
            await message.answer("❌ Подписка не найдена.")
            return

        current_expiry = parse_date_value(sub.expiry_date)
        base_date = current_expiry if current_expiry and current_expiry >= today else today
        new_expiry = add_months(base_date, months)

        base_price = get_base_price(plan)
        current_bonus = int(getattr(user, "bonus_balance", 0) or 0)
        price_after_discount = apply_discount(base_price, int(discount_from_payload or 0))
        max_bonus_allowed = calc_bonus_to_use(price_after_discount, current_bonus)
        bonus_to_spend = min(int(bonus_reserved or 0), int(max_bonus_allowed), int(current_bonus))

        if price_after_discount - bonus_to_spend < MIN_PAY_RUB:
            bonus_to_spend = max(0, price_after_discount - MIN_PAY_RUB)

        if bonus_to_spend > 0:
            user.bonus_balance = current_bonus - bonus_to_spend

        session.add(
            Payments(
                tg_id=tg_id,
                username=username,
                price=paid_rub,
                date=datetime.now(),
                tarific_plan=plan,
                provider_payment_charge_id=provider_payment_charge_id,
            )
        )

        await session.execute(
            update(Subscribers)
            .where(Subscribers.id == sub_id)
            .values(
                expiry_date=new_expiry.isoformat(),
                subscription=plan,
                notif_oneday=False,
            )
        )

        await mark_promo_used_if_applicable(session, tg_id, is_first_payment)
        await refresh_user_protocol(session, tg_id)
        await session.commit()

        protocol = get_record_protocol(sub)
        was_expired = current_expiry is None or current_expiry < today
        logger.info(
            "Успешное продление: tg_id=%s sub_id=%s protocol=%s new_expiry=%s charge=%s",
            tg_id, sub_id, protocol, new_expiry, provider_payment_charge_id,
        )

    restore_message = ""
    try:
        async with async_session.begin() as session:
            await session.execute(text("BEGIN IMMEDIATE"))
            current = await session.get(Subscribers, sub_id)
            if current is not None:
                if was_expired:
                    access = await create_vpn_access(
                        protocol=get_record_protocol(current), client_name=current.file_name,
                        expiry_date=current.expiry_date, tg_id=tg_id,
                        username=username, xui_sub_id=current.xui_sub_id,
                    )
                    current.xui_sub_id = access.xui_sub_id
                else:
                    access = None
                    await update_vpn_expiry(
                        protocol=get_record_protocol(current), client_name=current.file_name,
                        expiry_date=current.expiry_date,
                    )
            else:
                access = None
        if access is not None:
            await send_access_to_user(message, access)
    except Exception:
        logger.exception("Не удалось синхронизировать продление: tg_id=%s sub_id=%s", tg_id, sub_id)
        restore_message = "\n⚠️ Не удалось обновить доступ на сервере. Напишите в поддержку."

    await message.answer(
        "✅ <b>Подписка продлена!</b>\n\n"
        f"🛡️ <b>Протокол:</b> {get_protocol_label(protocol)}\n"
        f"💳 <b>Тариф:</b> {RENEW_LABELS[plan]}\n"
        f"💰 <b>Списано бонусов:</b> {bonus_to_spend} ₽\n"
        f"⏳ <b>Активна до:</b> <b>{new_expiry.isoformat()}</b>"
        f"{restore_message}",
        parse_mode="HTML",
    )
