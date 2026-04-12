import asyncio
import json
import logging
from datetime import datetime
from typing import Optional

import config
from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, FSInputFile, LabeledPrice, Message, PreCheckoutQuery
from sqlalchemy import select, update

from app.addons.utilits import calculate_expiry_date, check_available_clients_count, generate_client_name
from app.database.models import Payments, Referral, Server, Subscribers, User, async_session
from app.payments.pricing import (
    CALLBACK_TO_PAYLOAD_PLAN,
    MIN_PAY_RUB,
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
from app.wg_api.wg_api import add_client_wg, get_config_wg

pay_router = Router()
logger = logging.getLogger(__name__)


def _parse_callback_data(data: str) -> tuple[Optional[str], Optional[str], Optional[int]]:
    parts = (data or "").split("|")
    if len(parts) < 3:
        return None, None, None

    callback_plan, region, region_id_str = parts[0], parts[1], parts[2]
    if callback_plan not in CALLBACK_TO_PAYLOAD_PLAN:
        return None, None, None
    if not region_id_str.isdigit():
        return None, None, None
    return callback_plan, region, int(region_id_str)


async def _get_server(session, region: str, region_id: int) -> Optional[Server]:
    result = await session.execute(
        select(Server).where(
            Server.region == region,
            Server.region_id == region_id,
            Server.is_active == True,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()


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


@pay_router.callback_query(
    F.data.startswith("one_month|")
    | F.data.startswith("six_month|")
    | F.data.startswith("twelve_month|")
)
async def create_invoice_any(call: CallbackQuery):
    callback_plan, region, region_id = _parse_callback_data(call.data)
    if not callback_plan or not region or region_id is None:
        await call.answer("❌ Ошибка данных.", show_alert=True)
        return

    plan = CALLBACK_TO_PAYLOAD_PLAN[callback_plan]
    base_price = get_base_price(plan)

    async with async_session() as session:
        discount = await get_active_discount_percent(session, call.from_user.id)
        bonus_balance = await get_user_bonus_balance(session, call.from_user.id)

    price_after_discount = apply_discount(base_price, discount)
    bonus_to_use = calc_bonus_to_use(price_after_discount, bonus_balance)
    final_pay_price = price_after_discount - bonus_to_use

    payload = build_buy_payload(
        base_plan=plan,
        region=region,
        region_id=region_id,
        discount=discount,
        bonus_used=bonus_to_use,
    )

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
        _, region, region_id, _, _ = parse_buy_payload(pre_checkout_query.invoice_payload)
    except ValueError:
        await bot.answer_pre_checkout_query(
            pre_checkout_query.id,
            ok=False,
            error_message="Некорректные данные платежа.",
        )
        return

    is_available = await check_available_clients_count(region=region, region_id=region_id)
    if is_available:
        await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)
        return

    await bot.answer_pre_checkout_query(
        pre_checkout_query.id,
        ok=False,
        error_message="К сожалению, на выбранном сервере нет свободных мест.",
    )


@pay_router.message(
    F.successful_payment.invoice_payload.startswith("monthly_subs")
    | F.successful_payment.invoice_payload.startswith("semi_annual_subs")
    | F.successful_payment.invoice_payload.startswith("annual_subs")
)
async def handle_successful_payment(message: Message):
    try:
        plan, region, region_id, discount_from_payload, bonus_reserved = parse_buy_payload(
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

    async with async_session() as session:
        prev_payments_count = await get_user_payments_count(session, tg_id)
        is_first_payment = prev_payments_count == 0

        user_result = await session.execute(select(User).where(User.tg_id == tg_id))
        user = user_result.scalar_one_or_none()
        if not user:
            logger.error(
                "Пользователь не найден при обработке успешного платежа: tg_id=%s plan=%s payment_charge_id=%s",
                tg_id,
                plan,
                provider_payment_charge_id,
            )
            await message.answer("❌ Пользователь не найден.")
            return

        current_bonus = int(getattr(user, "bonus_balance", 0) or 0)
        base_price = get_base_price(plan)
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
        await session.commit()

        expiry_date = await calculate_expiry_date(plan)
        client_name = generate_client_name()

        new_subscriber = Subscribers(
            tg_id=tg_id,
            username=username,
            file_name="pending",
            subscription=plan,
            expiry_date=expiry_date.isoformat(),
            server_region=region,
            server_region_id=region_id,
            notif_oneday=False,
        )
        session.add(new_subscriber)
        await session.flush()

        server = await _get_server(session, region, region_id)
        if not server:
            logger.error(
                "Сервер недоступен после успешного платежа: tg_id=%s plan=%s region=%s region_id=%s payment_charge_id=%s",
                tg_id,
                plan,
                region,
                region_id,
                provider_payment_charge_id,
            )
            await session.rollback()
            await message.answer(
                "⚠️ Оплата прошла, но сервер недоступен. Напишите в поддержку, мы вручную выдадим доступ."
            )
            return

        ip = f"https://{server.host_ip}:{server.port}"
        password = server.password

        try:
            await add_client_wg(client_name, ip, password)
            await get_config_wg(client_name, ip, password)
            await asyncio.sleep(1)
        except Exception:
            logger.exception(
                "Ошибка выдачи WG-конфига после успешной оплаты: tg_id=%s sub_id=%s client=%s region=%s region_id=%s payment_charge_id=%s",
                tg_id,
                new_subscriber.id,
                client_name,
                region,
                region_id,
                provider_payment_charge_id,
            )
            await session.rollback()
            await message.answer(
                "⚠️ Оплата прошла, но произошла ошибка выдачи конфигурации. Напишите в поддержку."
            )
            return

        await session.execute(
            update(Subscribers)
            .where(Subscribers.id == new_subscriber.id)
            .values(file_name=client_name, notif_oneday=False)
        )

        await mark_promo_used_if_applicable(session, tg_id, is_first_payment)
        if is_first_payment:
            await _apply_referral_bonus_if_applicable(session, tg_id, message.bot)

        await session.commit()
        logger.info(
            "Успешная покупка подписки: tg_id=%s username=%s sub_id=%s plan=%s amount_rub=%s bonus_spent=%s discount=%s region=%s region_id=%s expiry=%s payment_charge_id=%s",
            tg_id,
            username,
            new_subscriber.id,
            plan,
            paid_rub,
            bonus_to_spend,
            discount_from_payload,
            region,
            region_id,
            expiry_date.isoformat(),
            provider_payment_charge_id,
        )

    file_path = f"app/auth/{client_name}.conf"
    await message.answer(
        f"✅ Ваша подписка успешно оформлена до <b>{expiry_date.isoformat()}</b>.\n\n"
        f"📍 <b>Сервер:</b> {region} №{region_id}\n"
        f"💳 <b>Списано бонусов:</b> {bonus_to_spend} ₽",
        parse_mode="HTML",
    )
    await message.answer_document(FSInputFile(file_path))
