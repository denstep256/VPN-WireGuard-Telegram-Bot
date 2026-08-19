import json
import logging
import config
from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, FSInputFile, LabeledPrice, Message, PreCheckoutQuery
from sqlalchemy import func, select

from app.addons.utilits import add_months, parse_date_value, server_api_url
from app.database.models import Payments, Server, Subscribers, User, async_session
from app.payments.pricing import (
    PLAN_TO_MONTHS,
    apply_discount,
    build_provider_data,
    build_renew_payload,
    calc_bonus_to_use,
    calculate_invoice_price,
    get_active_discount_percent,
    get_base_price,
    get_user_payments_count,
    mark_promo_used_if_applicable,
    parse_renew_payload,
)
from app.payments.referrals import (
    apply_referral_bonus_if_applicable,
    notify_referral_bonus,
)
from app.time_utils import moscow_today, utc_now_naive
from app.wg_api.wg_api import provision_client_wg

renew_pay_router = Router()
logger = logging.getLogger(__name__)


def _renewal_note(charge_id: str, status: str) -> str:
    return f"renewal:{charge_id}:{status}"


def _validate_renewal_total(
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
        plan, sub_id, discount, bonus_reserved = parse_renew_payload(
            pre_checkout_query.invoice_payload
        )
        _validate_renewal_total(
            plan=plan,
            discount=discount,
            bonus_used=bonus_reserved,
            total_amount=pre_checkout_query.total_amount,
            currency=pre_checkout_query.currency,
        )
    except ValueError as exc:
        logger.warning(
            "Отклонён pre-checkout продления: tg_id=%s payload=%s reason=%s",
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
        user_res = await session.execute(
            select(User).where(User.tg_id == pre_checkout_query.from_user.id)
        )
        user = user_res.scalar_one_or_none()

    if not sub:
        await bot.answer_pre_checkout_query(
            pre_checkout_query.id,
            ok=False,
            error_message="Подписка не найдена.",
        )
        return

    if not user:
        await bot.answer_pre_checkout_query(
            pre_checkout_query.id,
            ok=False,
            error_message="Пользователь не найден. Перезапустите бота командой /start.",
        )
        return

    if bonus_reserved > int(user.bonus_balance or 0):
        await bot.answer_pre_checkout_query(
            pre_checkout_query.id,
            ok=False,
            error_message="Бонусный баланс изменился. Сформируйте новый счёт.",
        )
        return

    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)


@renew_pay_router.message(F.successful_payment.invoice_payload.startswith("renew|"))
async def handle_renew_success(message: Message):
    successful_payment = message.successful_payment
    try:
        plan, sub_id, discount_from_payload, bonus_reserved = parse_renew_payload(
            successful_payment.invoice_payload
        )
        paid_rub = _validate_renewal_total(
            plan=plan,
            discount=discount_from_payload,
            bonus_used=bonus_reserved,
            total_amount=successful_payment.total_amount,
            currency=successful_payment.currency,
        )
    except ValueError as exc:
        logger.critical(
            "Некорректный успешный платёж продления: tg_id=%s payload=%s reason=%s",
            message.from_user.id if message.from_user else None,
            successful_payment.invoice_payload,
            exc,
        )
        await message.answer(
            "⚠️ Платёж продления требует ручной проверки. Напишите в поддержку."
        )
        return

    tg_id = message.from_user.id
    username = message.from_user.username or "unknown"
    provider_payment_charge_id = successful_payment.provider_payment_charge_id
    if not provider_payment_charge_id:
        logger.critical("У продления отсутствует provider charge id: tg_id=%s sub_id=%s", tg_id, sub_id)
        await message.answer("⚠️ Не найден идентификатор платежа. Напишите в поддержку.")
        return

    months = PLAN_TO_MONTHS[plan]
    today = moscow_today()
    inviter_to_notify: int | None = None
    bonus_to_spend = int(bonus_reserved)

    async with async_session() as session:
        payment_res = await session.execute(
            select(Payments).where(
                Payments.provider_payment_charge_id == provider_payment_charge_id
            )
        )
        existing_payment = payment_res.scalar_one_or_none()
        if existing_payment and (
            int(existing_payment.tg_id) != tg_id
            or existing_payment.tarific_plan != plan
            or int(existing_payment.price) != paid_rub
        ):
            logger.critical(
                "Конфликт идентификатора продления: tg_id=%s stored_tg_id=%s charge_id=%s",
                tg_id,
                existing_payment.tg_id,
                provider_payment_charge_id,
            )
            await message.answer("⚠️ Обнаружен конфликт платежа. Напишите в поддержку.")
            return

        sub_res = await session.execute(
            select(Subscribers).where(Subscribers.id == sub_id, Subscribers.tg_id == tg_id)
        )
        sub = sub_res.scalar_one_or_none()
        if not sub:
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
                "Подписка не найдена при продлении: tg_id=%s sub_id=%s plan=%s payment_charge_id=%s",
                tg_id,
                sub_id,
                plan,
                provider_payment_charge_id,
            )
            await message.answer(
                "⚠️ Оплата зарегистрирована, но подписка не найдена. "
                "Напишите в поддержку для ручного продления."
            )
            return

        if existing_payment:
            completed_note = _renewal_note(provider_payment_charge_id, "completed")
            pending_note = _renewal_note(provider_payment_charge_id, "pending")
            if sub.note == completed_note:
                await message.answer("ℹ️ Это продление уже обработано повторно не начислено.")
                return
            if sub.note != pending_note:
                logger.critical(
                    "Повторное продление найдено без маркера: tg_id=%s sub_id=%s charge_id=%s note=%s",
                    tg_id,
                    sub_id,
                    provider_payment_charge_id,
                    sub.note,
                )
                await message.answer(
                    "⚠️ Платёж уже зарегистрирован, но продление требует ручной проверки. "
                    "Напишите в поддержку."
                )
                return
            earlier_payments = await session.scalar(
                select(func.count(Payments.id)).where(
                    Payments.tg_id == tg_id,
                    Payments.id < existing_payment.id,
                )
            )
            is_first_payment = int(earlier_payments or 0) == 0
            was_expired = True
            new_expiry = parse_date_value(sub.expiry_date)
            if new_expiry is None:
                logger.critical(
                    "Некорректная дата у pending-продления: tg_id=%s sub_id=%s expiry=%s",
                    tg_id,
                    sub_id,
                    sub.expiry_date,
                )
                await message.answer("⚠️ Некорректная дата подписки. Напишите в поддержку.")
                return
        else:
            user_res = await session.execute(select(User).where(User.tg_id == tg_id))
            user = user_res.scalar_one_or_none()
            if not user:
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
                    "Пользователь не найден при продлении: tg_id=%s sub_id=%s plan=%s payment_charge_id=%s",
                    tg_id,
                    sub_id,
                    plan,
                    provider_payment_charge_id,
                )
                await message.answer(
                    "⚠️ Оплата зарегистрирована, но профиль пользователя не найден. "
                    "Напишите в поддержку для ручного продления."
                )
                return

            prev_payments_count = await get_user_payments_count(session, tg_id)
            is_first_payment = prev_payments_count == 0
            current_expiry = parse_date_value(sub.expiry_date)
            was_expired = (
                current_expiry is None
                or current_expiry < today
                or str(sub.note or "").startswith("expired_")
            )
            base_date = current_expiry if current_expiry and not was_expired else today
            new_expiry = add_months(base_date, months)

            current_bonus = int(user.bonus_balance or 0)
            bonus_to_spend = min(int(bonus_reserved), current_bonus)
            if bonus_to_spend != int(bonus_reserved):
                logger.warning(
                    "Бонусный баланс изменился между pre-checkout и продлением: tg_id=%s reserved=%s actual=%s",
                    tg_id,
                    bonus_reserved,
                    current_bonus,
                )
            user.bonus_balance = current_bonus - bonus_to_spend

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
            sub.expiry_date = new_expiry.isoformat()
            sub.subscription = plan
            sub.notif_oneday = False
            sub.note = _renewal_note(
                provider_payment_charge_id,
                "pending" if was_expired else "completed",
            )

            await mark_promo_used_if_applicable(session, tg_id, is_first_payment)
            if is_first_payment:
                inviter_to_notify = await apply_referral_bonus_if_applicable(session, tg_id)
            await session.commit()

        server_region = sub.server_region
        server_region_id = sub.server_region_id
        file_name = sub.file_name

    if inviter_to_notify is not None:
        await notify_referral_bonus(message.bot, tg_id, inviter_to_notify)

    restore_message = ""
    if was_expired:
        async with async_session() as session:
            srv_res = await session.execute(
                select(Server).where(
                    Server.region == server_region,
                    Server.region_id == server_region_id,
                    Server.is_active.is_(True),
                )
            )
            server = srv_res.scalar_one_or_none()

        if not server:
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
                file_path = await provision_client_wg(
                    file_name,
                    server_api_url(server),
                    server.password,
                )
                async with async_session() as session:
                    renewed_sub = await session.get(Subscribers, sub_id)
                    if renewed_sub and renewed_sub.tg_id == tg_id:
                        renewed_sub.note = _renewal_note(
                            provider_payment_charge_id,
                            "completed",
                        )
                        await session.commit()
                await message.answer_document(FSInputFile(file_path))
            except Exception:
                logger.exception(
                    "Ошибка восстановления WG-конфига после продления: tg_id=%s sub_id=%s client=%s region=%s region_id=%s",
                    tg_id,
                    sub_id,
                    file_name,
                    server_region,
                    server_region_id,
                )
                restore_message = "\n⚠️ Не удалось автоматически восстановить конфигурацию. Напишите в поддержку."

    logger.info(
        "Успешное продление подписки: tg_id=%s username=%s sub_id=%s plan=%s months=%s amount_rub=%s bonus_spent=%s discount=%s new_expiry=%s was_expired=%s payment_charge_id=%s",
        tg_id,
        username,
        sub_id,
        plan,
        months,
        paid_rub,
        bonus_to_spend,
        discount_from_payload,
        new_expiry.isoformat(),
        was_expired,
        provider_payment_charge_id,
    )

    await message.answer(
        "✅ <b>Подписка продлена!</b>\n\n"
        f"📍 <b>Сервер:</b> {server_region} №{server_region_id}\n"
        f"💳 <b>Тариф:</b> {RENEW_LABELS[plan]}\n"
        f"💰 <b>Списано бонусов:</b> {bonus_to_spend} ₽\n"
        f"⏳ <b>Активна до:</b> <b>{new_expiry.isoformat()}</b>"
        f"{restore_message}",
        parse_mode="HTML",
    )
