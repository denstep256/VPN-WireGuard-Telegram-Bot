import json
import logging
from datetime import date, datetime

import config
from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, LabeledPrice, Message, PreCheckoutQuery
from sqlalchemy import select, update

from app.addons.utilits import add_months, parse_date_value
from app.database.models import Payments, Server, Subscribers, User, async_session
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
    PROTOCOL_WIREGUARD,
    format_service_location,
    get_protocol_label,
    get_record_protocol,
    restore_vpn_access,
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
            select(Subscribers).where(Subscribers.id == sub_id, Subscribers.tg_id == tg_id)
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
    today = date.today()

    async with async_session() as session:
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
            select(Subscribers).where(Subscribers.id == sub_id, Subscribers.tg_id == tg_id)
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
        await session.commit()

        server_region = sub.server_region
        server_region_id = sub.server_region_id
        file_name = sub.file_name
        protocol = get_record_protocol(sub)
        xui_sub_id = sub.xui_sub_id
        was_expired = current_expiry is None or current_expiry < today
        logger.info(
            "Успешное продление подписки: tg_id=%s username=%s sub_id=%s plan=%s protocol=%s months=%s amount_rub=%s bonus_spent=%s discount=%s new_expiry=%s was_expired=%s payment_charge_id=%s",
            tg_id,
            username,
            sub_id,
            plan,
            protocol,
            months,
            paid_rub,
            bonus_to_spend,
            discount_from_payload,
            new_expiry.isoformat(),
            was_expired,
            provider_payment_charge_id,
        )

    restore_message = ""
    if protocol != PROTOCOL_WIREGUARD and not was_expired:
        try:
            await update_vpn_expiry(
                protocol=protocol,
                client_name=file_name,
                expiry_date=new_expiry,
            )
        except Exception:
            logger.exception(
                "Ошибка синхронизации срока 3xUI после продления: tg_id=%s sub_id=%s client=%s",
                tg_id,
                sub_id,
                file_name,
            )
            restore_message = "\n⚠️ Не удалось синхронизировать срок в 3xUI. Напишите в поддержку."

    if was_expired:
        server = None
        if protocol == PROTOCOL_WIREGUARD:
            async with async_session() as session:
                srv_res = await session.execute(
                    select(Server).where(
                        Server.region == server_region,
                        Server.region_id == server_region_id,
                        Server.is_active == True,  # noqa: E712
                    )
                )
                server = srv_res.scalar_one_or_none()

        if protocol == PROTOCOL_WIREGUARD and not server:
            logger.error(
                "Не найден сервер для восстановления WG после продления: tg_id=%s sub_id=%s region=%s region_id=%s",
                tg_id,
                sub_id,
                server_region,
                server_region_id,
            )
            restore_message = "\n⚠️ Сервер для восстановления конфигурации недоступен. Напишите в поддержку."
        else:
            try:
                access = await restore_vpn_access(
                    protocol=protocol,
                    client_name=file_name,
                    expiry_date=new_expiry,
                    tg_id=tg_id,
                    username=username,
                    server=server,
                    xui_sub_id=xui_sub_id,
                )
                if access.xui_sub_id and access.xui_sub_id != xui_sub_id:
                    async with async_session() as session:
                        await session.execute(
                            update(Subscribers)
                            .where(Subscribers.id == sub_id)
                            .values(xui_sub_id=access.xui_sub_id)
                        )
                        await session.commit()
                await send_access_to_user(message, access)
            except Exception:
                logger.exception(
                    "Ошибка восстановления VPN-доступа после продления: tg_id=%s sub_id=%s client=%s protocol=%s region=%s region_id=%s",
                    tg_id,
                    sub_id,
                    file_name,
                    protocol,
                    server_region,
                    server_region_id,
                )
                restore_message = "\n⚠️ Не удалось автоматически восстановить конфигурацию. Напишите в поддержку."

    await message.answer(
        "✅ <b>Подписка продлена!</b>\n\n"
        f"🛡️ <b>Протокол:</b> {get_protocol_label(protocol)}\n"
        f"📍 <b>Сервис:</b> {format_service_location(protocol, server_region, server_region_id)}\n"
        f"💳 <b>Тариф:</b> {RENEW_LABELS[plan]}\n"
        f"💰 <b>Списано бонусов:</b> {bonus_to_spend} ₽\n"
        f"⏳ <b>Активна до:</b> <b>{new_expiry.isoformat()}</b>"
        f"{restore_message}",
        parse_mode="HTML",
    )
