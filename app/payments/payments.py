import asyncio
import json
from datetime import datetime
from typing import Optional, Tuple

from aiogram import Bot, Router, F
from aiogram.types import (
    Message,
    CallbackQuery,
    LabeledPrice,
    PreCheckoutQuery,
    FSInputFile,
)

from sqlalchemy import select, update, func

import config
from config import one_mounth_price, six_mounth_price, twelve_mounth_price

from app.database.models import (
    async_session,
    Subscribers,
    Payments,
    Server,
    User,
    Referral,
    PromoCode,
    PromoRedemption
)

from app.addons.utilits import (
    calculate_expiry_date,
    check_available_clients_count,
    generate_client_name,
)
from app.wg_api.wg_api import add_client_wg, get_config_wg

pay_router = Router()


# -----------------------------
# Tariff mapping (single source)
# -----------------------------
TARIFFS = {
    "one_month": {
        "payload_plan": "monthly_subs",
        "title": "Доступ к VPN на 1 мес.",
        "label": "Подписка на 1 месяц",
        "receipt_desc": "Подписка на 1 месяц",
        "price_rub": one_mounth_price,
    },
    "six_month": {
        "payload_plan": "semi_annual_subs",
        "title": "Доступ к VPN на 6 мес.",
        "label": "Подписка на 6 месяцев",
        "receipt_desc": "Подписка на 6 месяцев",
        "price_rub": six_mounth_price,
    },
    "twelve_month": {
        "payload_plan": "annual_subs",
        "title": "Доступ к VPN на 12 мес.",
        "label": "Подписка на 12 месяцев",
        "receipt_desc": "Подписка на 12 месяцев",
        "price_rub": twelve_mounth_price,
    },
}


# -----------------------------
# Helpers
# -----------------------------
def _build_payment_payload(base_plan: str, region: str, region_id: int, discount: int, bonus_used: int) -> str:
    # первые 3 части сохраняем как раньше: base_plan|region|region_id
    # дальше — параметры с префиксами, чтобы легко парсить
    return f"{base_plan}|{region}|{region_id}|d{discount}|b{bonus_used}"


def _parse_payment_payload(payload: str) -> tuple[str, str, int, int, int]:
    """
    Returns: (base_plan, region, region_id, discount_percent, bonus_used_reserved)
    """
    parts = (payload or "").split("|")
    if len(parts) < 3:
        raise ValueError("Invalid payload")

    base_plan = parts[0]
    region = parts[1]
    if not parts[2].isdigit():
        raise ValueError("Invalid region_id")
    region_id = int(parts[2])

    discount = 0
    bonus_used = 0
    for p in parts[3:]:
        if p.startswith("d") and p[1:].isdigit():
            discount = int(p[1:])
        elif p.startswith("b") and p[1:].isdigit():
            bonus_used = int(p[1:])

    return base_plan, region, region_id, discount, bonus_used



def _calc_bonus_to_use(price_after_discount: int, user_bonus_balance: int) -> int:
    """
    Сколько бонусов можно списать:
    - не больше баланса
    - так, чтобы к оплате осталось минимум 50₽
    """
    if price_after_discount <= config.MIN_PAY_RUB:
        return 0
    max_bonus_allowed = price_after_discount - config.MIN_PAY_RUB
    return max(0, min(int(user_bonus_balance or 0), max_bonus_allowed))


def _parse_callback_data(data: str) -> Tuple[Optional[str], Optional[str], Optional[int]]:
    """
    Expected: '<plan>|<region>|<region_id>'
    where plan is one of: one_month / six_month / twelve_month
    """
    parts = (data or "").split("|")
    if len(parts) < 3:
        return None, None, None

    plan, region, region_id_str = parts[0], parts[1], parts[2]
    if not region_id_str.isdigit():
        return None, None, None

    return plan, region, int(region_id_str)


def _build_provider_data(receipt_desc: str, price_rub: int) -> dict:
    return {
        "receipt": {
            "items": [
                {
                    "description": receipt_desc,
                    "quantity": "1.00",
                    "amount": {"value": f"{price_rub}.00", "currency": "RUB"},
                    "vat_code": 1,
                }
            ]
        }
    }


def _apply_discount(price_rub: int, discount_percent: int) -> int:
    if discount_percent <= 0:
        return price_rub
    # округление до рублей
    return int(round(price_rub * (100 - discount_percent) / 100))


async def _get_server(session, region: str, region_id: int) -> Optional[Server]:
    result = await session.execute(
        select(Server).where(
            Server.region == region,
            Server.region_id == region_id,
            Server.is_active == True,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()


async def _get_user_payments_count(session, tg_id: int) -> int:
    res = await session.execute(select(func.count(Payments.id)).where(Payments.tg_id == tg_id))
    return int(res.scalar() or 0)


async def _get_active_discount_percent(session, tg_id: int) -> int:
    """
    Находит активированный промокод (через PromoRedemption), проверяет правила.
    Сейчас достаточно: скидка 10% (или любая), ограничения first_purchase_only/max_uses_per_user.
    """
    q = (
        select(PromoRedemption, PromoCode)
        .join(PromoCode, PromoCode.id == PromoRedemption.promo_id)
        .where(
            PromoRedemption.user_tg_id == tg_id,
            PromoRedemption.is_activated == True,  # noqa: E712
            PromoCode.is_active == True,           # noqa: E712
        )
        .order_by(PromoRedemption.id.desc())
        .limit(1)
    )

    row = (await session.execute(q)).first()
    if not row:
        return 0

    redemption, promo = row

    # лимиты на пользователя
    if redemption.uses_count >= (promo.max_uses_per_user or 0):
        return 0

    # только на первую покупку
    if promo.first_purchase_only:
        cnt = await _get_user_payments_count(session, tg_id)
        if cnt > 0:
            return 0

    return int(promo.discount_percent or 0)


async def _mark_promo_used_if_applicable(session, tg_id: int, is_first_payment: bool) -> None:
    """
    После успешной оплаты:
    - если у пользователя есть активированный промокод, и он применим (first_purchase_only учитываем),
      увеличиваем uses_count, деактивируем (по умолчанию), ставим last_used_at.
    """
    q = (
        select(PromoRedemption, PromoCode)
        .join(PromoCode, PromoCode.id == PromoRedemption.promo_id)
        .where(
            PromoRedemption.user_tg_id == tg_id,
            PromoRedemption.is_activated == True,  # noqa: E712
            PromoCode.is_active == True,           # noqa: E712
        )
        .order_by(PromoRedemption.id.desc())
        .limit(1)
    )
    row = (await session.execute(q)).first()
    if not row:
        return

    redemption, promo = row

    if redemption.uses_count >= (promo.max_uses_per_user or 0):
        return

    if promo.first_purchase_only and not is_first_payment:
        return

    redemption.uses_count += 1
    redemption.is_activated = False
    redemption.last_used_at = datetime.utcnow()


async def _apply_referral_bonus_if_applicable(session, buyer_tg_id: int, bot: Bot) -> None:
    """
    Если buyer пришёл по рефке и это его первая покупка — начисляем 100₽ пригласившему (один раз).
    """
    ref_res = await session.execute(select(Referral).where(Referral.user_tg_id == buyer_tg_id))
    ref_row = ref_res.scalar_one_or_none()
    if not ref_row:
        return

    if not ref_row.invited_by_tg_id:
        return

    if ref_row.inviter_rewarded:
        return

    inviter_tg_id = int(ref_row.invited_by_tg_id)

    inviter_res = await session.execute(select(User).where(User.tg_id == inviter_tg_id))
    inviter = inviter_res.scalar_one_or_none()
    if not inviter:
        return

    inviter.bonus_balance = int(getattr(inviter, "bonus_balance", 0) or 0) + 100
    ref_row.inviter_rewarded = True

    # можно уведомить пригласившего (не критично)
    try:
        await bot.send_message(
            inviter_tg_id,
            "🎉 Ваш друг оформил первую подписку!\nВам начислено <b>100 ₽</b> на бонусный баланс.",
            parse_mode="HTML",
        )
    except Exception:
        pass


async def _send_invoice(
    call: CallbackQuery,
    *,
    payload: str,
    title: str,
    label: str,
    receipt_desc: str,
    price_rub: int,
    discount_percent: int = 0,
):
    provider_data = _build_provider_data(receipt_desc, price_rub)

    await call.bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)

    prices = [LabeledPrice(label=label, amount=price_rub * 100)]  # RUB -> kopeks

    base_desc = (
        "Оплата картой в Telegram 💳. В поле электронная почта укажите СВОЮ почту, "
        "на неё придет ваш чек об оплате."
    )
    if discount_percent > 0:
        base_desc = f"✅ Применена скидка {discount_percent}% по промокоду.\n\n" + base_desc

    await call.bot.send_invoice(
        chat_id=call.from_user.id,
        title=title,
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


# -----------------------------
# Single invoice handler for all 3 tariffs (+ promo discount)
# -----------------------------
@pay_router.callback_query(
    F.data.startswith("one_month|")
    | F.data.startswith("six_month|")
    | F.data.startswith("twelve_month|")
)
async def create_invoice_any(call: CallbackQuery):
    plan, region, region_id = _parse_callback_data(call.data)
    if not plan or not region or region_id is None:
        await call.answer("❌ Ошибка данных.", show_alert=True)
        return

    tariff = TARIFFS.get(plan)
    if not tariff:
        await call.answer("❌ Неизвестный тариф.", show_alert=True)
        return

    async with async_session() as session:
        # 1) скидка по промокоду
        discount = await _get_active_discount_percent(session, call.from_user.id)

        # 2) бонусный баланс пользователя
        ures = await session.execute(select(User).where(User.tg_id == call.from_user.id))
        user = ures.scalar_one_or_none()
        bonus_balance = int(getattr(user, "bonus_balance", 0) or 0)

    base_price = int(tariff["price_rub"])
    price_after_discount = _apply_discount(base_price, discount)

    # 3) бонусы
    bonus_to_use = _calc_bonus_to_use(price_after_discount, bonus_balance)
    final_pay_price = price_after_discount - bonus_to_use

    # 4) payload теперь содержит discount и бонусы
    payload = _build_payment_payload(
        base_plan=tariff["payload_plan"],
        region=region,
        region_id=region_id,
        discount=discount,
        bonus_used=bonus_to_use,
    )

    receipt_desc = tariff["receipt_desc"]
    extra_lines = []
    if discount > 0:
        receipt_desc = f"{receipt_desc} (скидка {discount}%)"
        extra_lines.append(f"✅ Скидка: {discount}%")
    if bonus_to_use > 0:
        extra_lines.append(f"💰 Списано бонусов: {bonus_to_use} ₽")
        extra_lines.append(f"💳 К оплате: {final_pay_price} ₽ (минимум {config.MIN_PAY_RUB} ₽)")

    # Передадим “инфо” в описание инвойса
    # (в _send_invoice оно подставится в description)
    if extra_lines:
        # вставим в receipt_desc тоже (не обязательно)
        receipt_desc = receipt_desc

    await _send_invoice(
        call,
        payload=payload,
        title=tariff["title"],
        label=tariff["label"],
        receipt_desc=receipt_desc,
        price_rub=final_pay_price,
        discount_percent=discount,
    )

# -----------------------------
# Pre-checkout
# -----------------------------
@pay_router.pre_checkout_query()
async def process_pre_checkout_query(pre_checkout_query: PreCheckoutQuery, bot: Bot):
    parts = (pre_checkout_query.invoice_payload or "").split("|")

    region = None
    region_id = None

    if len(parts) >= 3:
        _, region, region_id_str = parts[0], parts[1], parts[2]
        region_id = int(region_id_str) if region_id_str.isdigit() else None

    is_available = await check_available_clients_count(region=region, region_id=region_id)

    if is_available:
        await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)
    else:
        await bot.answer_pre_checkout_query(
            pre_checkout_query.id,
            ok=False,
            error_message="К сожалению, нет доступных файлов конфигурации на выбранном сервере.",
        )


# -----------------------------
# Successful payment (+ promo consume + referral bonus)
# -----------------------------
@pay_router.message(F.successful_payment)
async def handle_successful_payment(message: Message):
    try:
        base_payload, region, region_id, discount_from_payload, bonus_reserved = _parse_payment_payload(
            message.successful_payment.invoice_payload
        )
    except Exception:
        await message.answer("❌ Некорректный payload платежа.")
        return

    tg_id = message.from_user.id
    username = message.from_user.username or "unknown"

    paid_rub = int(message.successful_payment.total_amount / 100)  # фактически оплачено
    provider_payment_charge_id = message.successful_payment.provider_payment_charge_id

    async with async_session() as session:
        # первая покупка ДО вставки Payments
        prev_payments_count = await _get_user_payments_count(session, tg_id)
        is_first_payment = prev_payments_count == 0

        # --- Списываем бонусы в безопасном режиме ---
        # 1) получаем текущий баланс
        ures = await session.execute(select(User).where(User.tg_id == tg_id))
        user = ures.scalar_one_or_none()
        if not user:
            await message.answer("❌ Пользователь не найден.")
            return

        current_bonus = int(getattr(user, "bonus_balance", 0) or 0)

        # 2) восстановим “ожидаемую цену” после скидки из тарифа
        # base_payload = monthly_subs / semi_annual_subs / annual_subs
        # найдём цену
        price_map = {
            "monthly_subs": one_mounth_price,
            "semi_annual_subs": six_mounth_price,
            "annual_subs": twelve_mounth_price,
        }
        base_price = int(price_map.get(base_payload, paid_rub))

        price_after_discount = _apply_discount(base_price, int(discount_from_payload or 0))

        # 3) сколько бонусов МОЖНО списать по правилам
        max_bonus_allowed = _calc_bonus_to_use(price_after_discount, current_bonus)

        # 4) фактически списываем минимум из:
        # - то что “зарезервировали” в payload
        # - то что разрешено правилами (min 50)
        # - текущего баланса
        bonus_to_spend = min(int(bonus_reserved or 0), int(max_bonus_allowed), int(current_bonus))

        # 5) дополнительная страховка: платёж должен быть минимум 50₽
        # (на случай если что-то рассинхронизировалось)
        if price_after_discount - bonus_to_spend < config.MIN_PAY_RUB:
            bonus_to_spend = max(0, price_after_discount - config.MIN_PAY_RUB)

        # 6) списываем бонусы
        if bonus_to_spend > 0:
            user.bonus_balance = current_bonus - bonus_to_spend

        # 1) Payments — сохраняем ФАКТИЧЕСКИ оплаченную сумму
        new_payment = Payments(
            tg_id=tg_id,
            username=username,
            price=paid_rub,  # ✅ сколько реально оплатил в Telegram
            date=datetime.now(),
            tarific_plan=base_payload,
            provider_payment_charge_id=provider_payment_charge_id,
        )
        session.add(new_payment)
        await session.commit()

        # 2) Subscribers (как было)
        expiry_date = await calculate_expiry_date(base_payload)
        client_name = generate_client_name()

        new_subscriber = Subscribers(
            tg_id=tg_id,
            username=username,
            file_name="check",  # временно
            subscription=base_payload,
            expiry_date=expiry_date,
            server_region=region,
            server_region_id=region_id,
            notif_oneday=False,
        )
        session.add(new_subscriber)
        await session.flush()

        # 3) Server (как было)
        server = await _get_server(session, region, region_id)
        if not server:
            await message.answer("Сервер не найден", parse_mode="HTML")
            return

        ip = f"https://{server.host_ip}:{server.port}"
        password = server.password

        # 4) WG (как было)
        await add_client_wg(client_name, ip, password)
        await get_config_wg(client_name, ip, password)
        await asyncio.sleep(1)

        # 5) File (как было)
        file_path = f"app/auth/{client_name}.conf"
        document = FSInputFile(file_path)

        # 6) Update file_name (как было)
        await session.execute(
            update(Subscribers)
            .where(Subscribers.id == new_subscriber.id)
            .values(file_name=client_name)
        )

        # ✅ промокод: списать использование (если применим)
        await _mark_promo_used_if_applicable(session, tg_id, is_first_payment)

        # ✅ рефералка: начислить 100₽ пригласившему (только за первую покупку)
        if is_first_payment:
            await _apply_referral_bonus_if_applicable(session, tg_id, message.bot)

        await session.commit()

        # 7) Notify (как было)
        await message.answer(
            f"✅ Ваша подписка успешно оформлена до <b>{expiry_date}</b>.\n\n"
            f"Сервер: <b>{region} №{region_id}</b>\n\n"
            f"Файл конфигурации прикреплён ниже. Сохраните его!",
            parse_mode="HTML",
        )
        await message.answer_document(document)