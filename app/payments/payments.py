import asyncio
import json
import logging
from datetime import datetime
from hashlib import blake2s
from zoneinfo import ZoneInfo

import config
from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, LabeledPrice, Message, PreCheckoutQuery
from sqlalchemy import select, text

from app.addons.utilits import calculate_expiry_date, check_available_clients_count, generate_client_name, parse_date_value
from app.database.models import Payments, Referral, Subscribers, User, async_session, refresh_user_protocol
from app.payments.pricing import (
    CALLBACK_TO_PAYLOAD_PLAN,
    PLAN_LABELS,
    PLAN_RECEIPT_DESCRIPTIONS,
    PLAN_TITLES,
    apply_discount,
    build_buy_payload,
    build_provider_data,
    calc_bonus_to_use,
    get_active_discount_percent,
    get_base_price,
    get_user_bonus_balance,
    get_user_payments_count,
    mark_promo_used_if_applicable,
    parse_buy_payload,
)
from app.vpn.provisioning import (
    AccessResult,
    create_vpn_access,
    get_protocol_label,
    send_access_to_user,
)

pay_router = Router()
logger = logging.getLogger(__name__)


async def _apply_referral_bonus_if_applicable(session, buyer_tg_id: int, bot: Bot) -> None:
    ref_res = await session.execute(select(Referral).where(Referral.user_tg_id == buyer_tg_id))
    ref_row = ref_res.scalar_one_or_none()
    if not ref_row or not ref_row.invited_by_tg_id or ref_row.inviter_rewarded:
        return

    inviter_tg_id = int(ref_row.invited_by_tg_id)
    inviter_res = await session.execute(select(User).where(User.tg_id == inviter_tg_id))
    inviter = inviter_res.scalar_one_or_none()
    if not inviter:
        return

    inviter.bonus_balance = int(getattr(inviter, "bonus_balance", 0) or 0) + 100
    ref_row.inviter_rewarded = True

    try:
        await bot.send_message(
            inviter_tg_id,
            "🎉 Ваш друг оформил первую подписку!\nВам начислено <b>100 ₽</b> на бонусный баланс.",
            parse_mode="HTML",
        )
    except Exception:
        logger.exception(
            "Ошибка отправки уведомления рефералу: buyer_tg_id=%s inviter_tg_id=%s",
            buyer_tg_id,
            inviter_tg_id,
        )


async def _send_invoice(
    call: CallbackQuery,
    *,
    payload: str,
    plan: str,
    price_rub: int,
    discount_percent: int,
    bonus_used: int,
):
    receipt_desc = PLAN_RECEIPT_DESCRIPTIONS[plan]
    if discount_percent > 0:
        receipt_desc = f"{receipt_desc} (скидка {discount_percent}%)"
    provider_data = build_provider_data(receipt_desc, price_rub)

    prices = [LabeledPrice(label=PLAN_LABELS[plan], amount=int(price_rub) * 100)]

    details: list[str] = []
    if discount_percent > 0:
        details.append(f"✅ Применена скидка {discount_percent}%")
    if bonus_used > 0:
        details.append(f"💰 Списано бонусов: {bonus_used} ₽")

    base_desc = (
        "Оплата картой в Telegram 💳.\n"
        "В поле электронная почта укажите СВОЮ почту, на неё придет чек."
    )
    if details:
        base_desc = "\n".join(details) + "\n\n" + base_desc

    await call.bot.send_invoice(
        chat_id=call.from_user.id,
        title=PLAN_TITLES[plan],
        description=base_desc,
        payload=payload,
        provider_token=config.PAYMENT_TOKEN,
        currency="RUB",
        prices=prices,
        start_parameter="subscription",
        need_email=True,
        send_email_to_provider=True,
        provider_data=json.dumps(provider_data),
    )


@pay_router.callback_query(F.data.split("|")[0].in_(CALLBACK_TO_PAYLOAD_PLAN))
async def create_invoice_any(call: CallbackQuery):
    plan = CALLBACK_TO_PAYLOAD_PLAN[call.data.split("|", 1)[0]]
    base_price = get_base_price(plan)

    async with async_session() as session:
        discount = await get_active_discount_percent(session, call.from_user.id)
        bonus_balance = await get_user_bonus_balance(session, call.from_user.id)

    price_after_discount = apply_discount(base_price, discount)
    bonus_to_use = calc_bonus_to_use(price_after_discount, bonus_balance)
    final_pay_price = price_after_discount - bonus_to_use

    payload = build_buy_payload(plan, discount, bonus_to_use)

    await _send_invoice(
        call,
        payload=payload,
        plan=plan,
        price_rub=final_pay_price,
        discount_percent=discount,
        bonus_used=bonus_to_use,
    )
    await call.answer()


@pay_router.pre_checkout_query(
    F.invoice_payload.startswith("monthly_subs")
    | F.invoice_payload.startswith("semi_annual_subs")
    | F.invoice_payload.startswith("annual_subs")
)
async def process_pre_checkout_query(pre_checkout_query: PreCheckoutQuery, bot: Bot):
    try:
        _, protocol, _, _ = parse_buy_payload(pre_checkout_query.invoice_payload)
    except ValueError:
        await bot.answer_pre_checkout_query(
            pre_checkout_query.id,
            ok=False,
            error_message="Некорректные данные платежа.",
        )
        return

    try:
        async with asyncio.timeout(8):
            is_available = await check_available_clients_count(protocol)
    except Exception:
        logger.exception(
            "Ошибка проверки доступности перед платежом: tg_id=%s protocol=%s",
            pre_checkout_query.from_user.id,
            protocol,
        )
        is_available = False

    if is_available:
        await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)
        return

    await bot.answer_pre_checkout_query(
        pre_checkout_query.id,
        ok=False,
        error_message="К сожалению, выбранный VPN-сервис сейчас недоступен.",
    )


async def issue_subscription(client_name: str, tg_id: int) -> tuple[AccessResult, str] | None:
    async with async_session.begin() as session:
        await session.execute(text("BEGIN IMMEDIATE"))
        sub = await session.scalar(select(Subscribers).where(
            Subscribers.file_name == client_name, Subscribers.tg_id == tg_id,
        ))
        if sub is None or sub.provisioned:
            return None
        expiry_date = parse_date_value(sub.expiry_date)
        if expiry_date is None or expiry_date < datetime.now(ZoneInfo(config.VPN_TIMEZONE)).date():
            raise ValueError("Срок оплаченного доступа уже истёк.")
        access = await create_vpn_access(
            protocol=sub.protocol, client_name=sub.file_name, expiry_date=sub.expiry_date,
            tg_id=tg_id, username=sub.username, xui_sub_id=sub.xui_sub_id,
        )
        sub.xui_sub_id = access.xui_sub_id
        sub.provisioned = True
        await refresh_user_protocol(session, tg_id)
        return access, sub.expiry_date


@pay_router.message(
    F.successful_payment.invoice_payload.startswith("monthly_subs")
    | F.successful_payment.invoice_payload.startswith("semi_annual_subs")
    | F.successful_payment.invoice_payload.startswith("annual_subs")
)
async def handle_successful_payment(message: Message):
    try:
        plan, protocol, discount_from_payload, bonus_reserved = parse_buy_payload(
            message.successful_payment.invoice_payload
        )
    except ValueError:
        logger.error(
            "Некорректный payload успешного платежа: tg_id=%s payload=%s",
            message.from_user.id if message.from_user else None,
            message.successful_payment.invoice_payload,
        )
        await message.answer("❌ Некорректный payload платежа.")
        return

    tg_id = message.from_user.id
    username = message.from_user.username or "unknown"
    paid_rub = int(message.successful_payment.total_amount / 100)
    provider_payment_charge_id = message.successful_payment.provider_payment_charge_id

    bonus_spent = None

    async with async_session.begin() as session:
        await session.execute(text("BEGIN IMMEDIATE"))
        paid = await session.scalar(select(Payments.id).where(
            Payments.provider_payment_charge_id == provider_payment_charge_id,
        ).limit(1))
        if paid is not None:
            client_name = await session.scalar(select(Subscribers.file_name).where(
                Subscribers.purchase_charge_id == provider_payment_charge_id, Subscribers.tg_id == tg_id,
            ))
            if client_name is None:
                # Purchases made before numeric names used a deterministic name.
                digest = blake2s(provider_payment_charge_id.encode(), digest_size=8).hexdigest()
                client_name = f"ZENITH-{digest}"
        else:
            client_name = await generate_client_name(session)
            user = await session.scalar(select(User).where(User.tg_id == tg_id))
            if user is None:
                logger.error("Пользователь %s не найден для платежа %s", tg_id, provider_payment_charge_id)
                await message.answer("❌ Пользователь не найден.")
                return

            is_first_payment = await get_user_payments_count(session, tg_id) == 0
            current_bonus = int(user.bonus_balance or 0)
            discounted = apply_discount(get_base_price(plan), discount_from_payload)
            bonus_spent = min(bonus_reserved, calc_bonus_to_use(discounted, current_bonus))
            user.bonus_balance = current_bonus - bonus_spent
            session.add(Payments(
                tg_id=tg_id, username=username, price=paid_rub, date=datetime.now(),
                tarific_plan=plan, provider_payment_charge_id=provider_payment_charge_id,
            ))
            session.add(Subscribers(
                tg_id=tg_id, username=username, file_name=client_name, subscription=plan,
                expiry_date=(await calculate_expiry_date(plan)).isoformat(),
                server_region="", server_region_id=0, protocol=protocol,
                notif_oneday=False, provisioned=False, purchase_charge_id=provider_payment_charge_id,
            ))
            await mark_promo_used_if_applicable(session, tg_id, is_first_payment)
            if is_first_payment:
                await _apply_referral_bonus_if_applicable(session, tg_id, message.bot)

    try:
        result = await issue_subscription(client_name, tg_id)
        if result is None:
            return
        access, expiry = result
    except Exception:
        logger.exception(
            "Ошибка выдачи оплаченного доступа: tg_id=%s client=%s charge=%s",
            tg_id, client_name, provider_payment_charge_id,
        )
        await message.answer(
            "⚠️ Оплата прошла. Повторите выдачу в «Моих подписках» или напишите в поддержку."
        )
        return

    bonus_text = f"\n💳 <b>Списано бонусов:</b> {bonus_spent} ₽" if bonus_spent else ""
    await message.answer(
        f"✅ Ваша подписка успешно оформлена до <b>{expiry}</b>.\n"
        f"🛡️ {get_protocol_label(access.protocol)}{bonus_text}",
        parse_mode="HTML",
    )
    await send_access_to_user(message, access)
