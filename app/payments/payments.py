import json
import logging
from typing import Optional

import config
from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, FSInputFile, LabeledPrice, Message, PreCheckoutQuery
from sqlalchemy import func, select

from app.addons.utilits import (
    calculate_expiry_date,
    check_available_clients_count,
    generate_client_name,
    server_api_url,
)
from app.database.models import Payments, Server, Subscribers, User, async_session
from app.paths import config_file_path
from app.payments.pricing import (
    CALLBACK_TO_PAYLOAD_PLAN,
    PLAN_LABELS,
    PLAN_RECEIPT_DESCRIPTIONS,
    PLAN_TITLES,
    apply_discount,
    build_buy_payload,
    build_provider_data,
    calc_bonus_to_use,
    calculate_invoice_price,
    get_active_discount_percent,
    get_base_price,
    get_user_bonus_balance,
    get_user_payments_count,
    mark_promo_used_if_applicable,
    parse_buy_payload,
)
from app.payments.referrals import (
    apply_referral_bonus_if_applicable,
    notify_referral_bonus,
)
from app.time_utils import utc_now_naive
from app.wg_api.wg_api import provision_client_wg

pay_router = Router()
logger = logging.getLogger(__name__)
PAYMENT_NOTE_PREFIX = "payment"


def _parse_callback_data(data: str) -> tuple[Optional[str], Optional[str], Optional[int]]:
    parts = (data or "").split("|")
    if len(parts) != 3:
        return None, None, None

    callback_plan, region, region_id_str = parts[0], parts[1], parts[2]
    if callback_plan not in CALLBACK_TO_PAYLOAD_PLAN or not region:
        return None, None, None
    if not region_id_str.isdigit():
        return None, None, None
    region_id = int(region_id_str)
    if region_id <= 0:
        return None, None, None
    return callback_plan, region, region_id


async def _get_server(session, region: str, region_id: int) -> Optional[Server]:
    result = await session.execute(
        select(Server).where(
            Server.region == region,
            Server.region_id == region_id,
            Server.is_active.is_(True),
        )
    )
    return result.scalar_one_or_none()


def _payment_note(charge_id: str, status: str) -> str:
    return f"{PAYMENT_NOTE_PREFIX}:{charge_id}:{status}"


async def _get_payment_subscription(
    session,
    charge_id: str,
    tg_id: int,
) -> Subscribers | None:
    result = await session.execute(
        select(Subscribers).where(
            Subscribers.tg_id == tg_id,
            Subscribers.note.in_(
                (
                    _payment_note(charge_id, "pending"),
                    _payment_note(charge_id, "completed"),
                )
            )
        )
    )
    return result.scalar_one_or_none()


def _validate_payment_total(
    *,
    plan: str,
    discount: int,
    bonus_used: int,
    total_amount: int,
    currency: str,
) -> int:
    if currency.upper() != "RUB":
        raise ValueError("Unsupported payment currency")
    expected_rub = calculate_invoice_price(plan, discount, bonus_used)
    if int(total_amount) != expected_rub * 100:
        raise ValueError(
            f"Unexpected payment amount: expected={expected_rub * 100}, actual={total_amount}"
        )
    return expected_rub


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
        server = await _get_server(session, region, region_id)
        if not server:
            await call.answer("❌ Сервер не найден или недоступен.", show_alert=True)
            return
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
        plan, region, region_id, discount, bonus_reserved = parse_buy_payload(
            pre_checkout_query.invoice_payload
        )
        _validate_payment_total(
            plan=plan,
            discount=discount,
            bonus_used=bonus_reserved,
            total_amount=pre_checkout_query.total_amount,
            currency=pre_checkout_query.currency,
        )
    except ValueError as exc:
        logger.warning(
            "Отклонён pre-checkout покупки: tg_id=%s payload=%s reason=%s",
            pre_checkout_query.from_user.id,
            pre_checkout_query.invoice_payload,
            exc,
        )
        await bot.answer_pre_checkout_query(
            pre_checkout_query.id,
            ok=False,
            error_message="Некорректные данные платежа.",
        )
        return

    async with async_session() as session:
        server = await _get_server(session, region, region_id)
        bonus_balance = await get_user_bonus_balance(session, pre_checkout_query.from_user.id)

    if not server:
        await bot.answer_pre_checkout_query(
            pre_checkout_query.id,
            ok=False,
            error_message="Выбранный сервер больше недоступен.",
        )
        return

    if bonus_reserved > bonus_balance:
        await bot.answer_pre_checkout_query(
            pre_checkout_query.id,
            ok=False,
            error_message="Бонусный баланс изменился. Сформируйте новый счёт.",
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
    successful_payment = message.successful_payment
    try:
        plan, region, region_id, discount_from_payload, bonus_reserved = parse_buy_payload(
            successful_payment.invoice_payload
        )
        paid_rub = _validate_payment_total(
            plan=plan,
            discount=discount_from_payload,
            bonus_used=bonus_reserved,
            total_amount=successful_payment.total_amount,
            currency=successful_payment.currency,
        )
    except ValueError as exc:
        logger.critical(
            "Некорректный успешный платёж: tg_id=%s payload=%s reason=%s",
            message.from_user.id if message.from_user else None,
            successful_payment.invoice_payload,
            exc,
        )
        await message.answer(
            "⚠️ Платёж получен с некорректными параметрами. "
            "Доступ автоматически не выдан — срочно напишите в поддержку."
        )
        return

    tg_id = message.from_user.id
    username = message.from_user.username or "unknown"
    provider_payment_charge_id = successful_payment.provider_payment_charge_id
    if not provider_payment_charge_id:
        logger.critical("У успешного платежа отсутствует provider charge id: tg_id=%s", tg_id)
        await message.answer("⚠️ Не найден идентификатор платежа. Напишите в поддержку.")
        return

    inviter_to_notify: int | None = None
    bonus_to_spend = int(bonus_reserved)

    async with async_session() as session:
        payment_result = await session.execute(
            select(Payments).where(
                Payments.provider_payment_charge_id == provider_payment_charge_id
            )
        )
        existing_payment = payment_result.scalar_one_or_none()

        if existing_payment:
            if (
                int(existing_payment.tg_id) != tg_id
                or existing_payment.tarific_plan != plan
                or int(existing_payment.price) != paid_rub
            ):
                logger.critical(
                    "Конфликт идентификатора платежа: tg_id=%s stored_tg_id=%s charge_id=%s",
                    tg_id,
                    existing_payment.tg_id,
                    provider_payment_charge_id,
                )
                await message.answer("⚠️ Обнаружен конфликт платежа. Напишите в поддержку.")
                return
            subscriber = await _get_payment_subscription(
                session,
                provider_payment_charge_id,
                tg_id,
            )
            if not subscriber:
                logger.critical(
                    "Повторный платёж найден без связанной подписки: tg_id=%s payment_id=%s charge_id=%s",
                    tg_id,
                    existing_payment.id,
                    provider_payment_charge_id,
                )
                await message.answer(
                    "⚠️ Платёж уже зарегистрирован, но подписка требует ручной проверки. "
                    "Напишите в поддержку."
                )
                return

            if subscriber.note == _payment_note(provider_payment_charge_id, "completed"):
                await message.answer("ℹ️ Этот платёж уже обработан, подписка повторно не начислена.")
                file_path = config_file_path(subscriber.file_name)
                if file_path.exists():
                    await message.answer_document(FSInputFile(file_path))
                return

            earlier_payments = await session.scalar(
                select(func.count(Payments.id)).where(
                    Payments.tg_id == tg_id,
                    Payments.id < existing_payment.id,
                )
            )
            is_first_payment = int(earlier_payments or 0) == 0
            expiry_date = subscriber.expiry_date
            client_name = subscriber.file_name
        else:
            prev_payments_count = await get_user_payments_count(session, tg_id)
            is_first_payment = prev_payments_count == 0

        user_result = await session.execute(select(User).where(User.tg_id == tg_id))
        user = user_result.scalar_one_or_none()
        if not user:
            if not existing_payment:
                session.add(
                    Payments(
                        tg_id=tg_id,
                        username=username,
                        price=paid_rub,
                        date=utc_now_naive().isoformat(timespec="seconds"),
                        tarific_plan=plan,
                        provider_payment_charge_id=provider_payment_charge_id,
                    )
                )
                await session.commit()
            logger.critical(
                "Пользователь не найден при обработке успешного платежа: tg_id=%s plan=%s payment_charge_id=%s",
                tg_id,
                plan,
                provider_payment_charge_id,
            )
            await message.answer(
                "⚠️ Оплата зарегистрирована, но профиль пользователя не найден. "
                "Напишите в поддержку для ручной выдачи доступа."
            )
            return

        if not existing_payment:
            current_bonus = int(getattr(user, "bonus_balance", 0) or 0)
            bonus_to_spend = min(int(bonus_reserved), current_bonus)
            if bonus_to_spend != int(bonus_reserved):
                logger.warning(
                    "Бонусный баланс изменился между pre-checkout и оплатой: tg_id=%s reserved=%s actual=%s",
                    tg_id,
                    bonus_reserved,
                    current_bonus,
                )
            user.bonus_balance = current_bonus - bonus_to_spend

            expiry = calculate_expiry_date(plan)
            expiry_date = expiry.isoformat()
            client_name = generate_client_name()
            session.add(
                Payments(
                    tg_id=tg_id,
                    username=username,
                    price=paid_rub,
                    date=utc_now_naive().isoformat(timespec="seconds"),
                    tarific_plan=plan,
                    provider_payment_charge_id=provider_payment_charge_id,
                )
            )
            subscriber = Subscribers(
                tg_id=tg_id,
                username=username,
                file_name=client_name,
                subscription=plan,
                expiry_date=expiry_date,
                server_region=region,
                server_region_id=region_id,
                notif_oneday=False,
                note=_payment_note(provider_payment_charge_id, "pending"),
            )
            session.add(subscriber)
            await session.commit()
            await session.refresh(subscriber)

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
            await message.answer(
                "⚠️ Оплата зарегистрирована, но сервер временно недоступен. "
                "Подписка сохранена в ожидании выдачи; напишите в поддержку."
            )
            return

        subscriber_id = int(subscriber.id)
        api_url = server_api_url(server)
        server_password = server.password

    try:
        file_path = await provision_client_wg(client_name, api_url, server_password)
    except Exception:
        logger.exception(
            "Ошибка выдачи WG-конфига после успешной оплаты: tg_id=%s sub_id=%s client=%s region=%s region_id=%s payment_charge_id=%s",
            tg_id,
            subscriber_id,
            client_name,
            region,
            region_id,
            provider_payment_charge_id,
        )
        await message.answer(
            "⚠️ Оплата зарегистрирована, но конфигурацию пока выдать не удалось. "
            "Повторите попытку через поддержку — подписка не будет начислена дважды."
        )
        return

    async with async_session() as session:
        sub_result = await session.execute(
            select(Subscribers).where(
                Subscribers.id == subscriber_id,
                Subscribers.tg_id == tg_id,
            )
        )
        subscriber = sub_result.scalar_one_or_none()
        if not subscriber:
            logger.critical(
                "Подписка исчезла во время выдачи WG-конфига: tg_id=%s sub_id=%s charge_id=%s",
                tg_id,
                subscriber_id,
                provider_payment_charge_id,
            )
            await message.answer("⚠️ Подписка требует ручной проверки. Напишите в поддержку.")
            return

        subscriber.note = _payment_note(provider_payment_charge_id, "completed")
        await mark_promo_used_if_applicable(session, tg_id, is_first_payment)
        if is_first_payment:
            inviter_to_notify = await apply_referral_bonus_if_applicable(session, tg_id)
        await session.commit()

    if inviter_to_notify is not None:
        await notify_referral_bonus(message.bot, tg_id, inviter_to_notify)

    logger.info(
        "Успешная покупка подписки: tg_id=%s username=%s sub_id=%s plan=%s amount_rub=%s bonus_spent=%s discount=%s region=%s region_id=%s expiry=%s payment_charge_id=%s",
        tg_id,
        username,
        subscriber_id,
        plan,
        paid_rub,
        bonus_to_spend,
        discount_from_payload,
        region,
        region_id,
        expiry_date,
        provider_payment_charge_id,
    )
    await message.answer(
        f"✅ Ваша подписка успешно оформлена до <b>{expiry_date}</b>.\n\n"
        f"📍 <b>Сервер:</b> {region} №{region_id}\n"
        f"💳 <b>Списано бонусов:</b> {bonus_to_spend} ₽",
        parse_mode="HTML",
    )
    await message.answer_document(FSInputFile(file_path))
