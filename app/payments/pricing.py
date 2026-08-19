from __future__ import annotations

import config
from sqlalchemy import func, select

from config import (
    one_mounth_price,
    one_mounth_fake_price,
    six_mounth_price,
    six_mounth_fake_price,
    twelve_mounth_price,
    twelve_mounth_fake_price,
)

from app.database.models import Payments, PromoCode, PromoRedemption, User
from app.time_utils import utc_now_naive


MIN_PAY_RUB = int(getattr(config, "MIN_PAY_RUB", 50))

CALLBACK_TO_PAYLOAD_PLAN = {
    "one_month": "monthly_subs",
    "six_month": "semi_annual_subs",
    "twelve_month": "annual_subs",
}

PAYLOAD_PLAN_TO_CALLBACK = {v: k for k, v in CALLBACK_TO_PAYLOAD_PLAN.items()}

PLAN_TO_MONTHS = {
    "monthly_subs": 1,
    "semi_annual_subs": 6,
    "annual_subs": 12,
}

PLAN_TITLES = {
    "monthly_subs": "Доступ к VPN на 1 мес.",
    "semi_annual_subs": "Доступ к VPN на 6 мес.",
    "annual_subs": "Доступ к VPN на 12 мес.",
}

PLAN_LABELS = {
    "monthly_subs": "Подписка на 1 месяц",
    "semi_annual_subs": "Подписка на 6 месяцев",
    "annual_subs": "Подписка на 12 месяцев",
}

PLAN_RECEIPT_DESCRIPTIONS = {
    "monthly_subs": "Подписка на 1 месяц",
    "semi_annual_subs": "Подписка на 6 месяцев",
    "annual_subs": "Подписка на 12 месяцев",
}

PLAN_PERIOD_LABELS = {
    "monthly_subs": "1 мес.",
    "semi_annual_subs": "6 мес.",
    "annual_subs": "12 мес.",
}

PLAN_PRICES = {
    "monthly_subs": int(one_mounth_price),
    "semi_annual_subs": int(six_mounth_price),
    "annual_subs": int(twelve_mounth_price),
}

PLAN_FAKE_PRICES = {
    "monthly_subs": int(one_mounth_fake_price),
    "semi_annual_subs": int(six_mounth_fake_price),
    "annual_subs": int(twelve_mounth_fake_price),
}

PLAN_ORDER = ("monthly_subs", "semi_annual_subs", "annual_subs")
MAX_DISCOUNT_PERCENT = 90


def apply_discount(price_rub: int, discount_percent: int) -> int:
    price = int(price_rub)
    discount = int(discount_percent)
    if price < 0:
        raise ValueError("Price cannot be negative")
    if not 0 <= discount <= MAX_DISCOUNT_PERCENT:
        raise ValueError(f"Discount must be between 0 and {MAX_DISCOUNT_PERCENT}")
    if discount == 0:
        return price
    return int(round(price * (100 - discount) / 100))


def calc_bonus_to_use(price_after_discount: int, user_bonus_balance: int) -> int:
    if int(price_after_discount) <= MIN_PAY_RUB:
        return 0
    max_bonus_allowed = int(price_after_discount) - MIN_PAY_RUB
    return max(0, min(int(user_bonus_balance or 0), max_bonus_allowed))


def calculate_invoice_price(plan: str, discount: int, bonus_used: int) -> int:
    discounted_price = apply_discount(get_base_price(plan), discount)
    max_bonus = calc_bonus_to_use(discounted_price, bonus_used)
    if int(bonus_used) != max_bonus:
        raise ValueError("Invalid bonus amount in payment payload")
    return discounted_price - max_bonus


def build_buy_payload(base_plan: str, region: str, region_id: int, discount: int, bonus_used: int) -> str:
    if base_plan not in PLAN_TO_MONTHS:
        raise ValueError(f"Unknown plan: {base_plan}")
    if not region or "|" in region:
        raise ValueError("Invalid region")
    if int(region_id) <= 0:
        raise ValueError("Invalid region id")
    calculate_invoice_price(base_plan, int(discount), int(bonus_used))
    return f"{base_plan}|{region}|{region_id}|d{discount}|b{bonus_used}"


def parse_buy_payload(payload: str) -> tuple[str, str, int, int, int]:
    parts = (payload or "").split("|")
    if len(parts) < 3:
        raise ValueError("Invalid payload")

    base_plan = parts[0]
    region = parts[1]
    if base_plan not in PLAN_TO_MONTHS or not region or not parts[2].isdigit():
        raise ValueError("Invalid region id")
    region_id = int(parts[2])
    if region_id <= 0:
        raise ValueError("Invalid region id")

    discount = 0
    bonus_used = 0
    for part in parts[3:]:
        if part.startswith("d") and part[1:].isdigit():
            discount = int(part[1:])
        elif part.startswith("b") and part[1:].isdigit():
            bonus_used = int(part[1:])
        else:
            raise ValueError("Invalid payload option")

    calculate_invoice_price(base_plan, discount, bonus_used)
    return base_plan, region, region_id, discount, bonus_used


def build_renew_payload(plan: str, sub_id: int, discount: int, bonus_used: int) -> str:
    if plan not in PLAN_TO_MONTHS or int(sub_id) <= 0:
        raise ValueError("Invalid renewal payload")
    calculate_invoice_price(plan, int(discount), int(bonus_used))
    return f"renew|{plan}|{sub_id}|d{discount}|b{bonus_used}"


def parse_renew_payload(payload: str) -> tuple[str, int, int, int]:
    parts = (payload or "").split("|")
    if len(parts) < 3 or parts[0] != "renew":
        raise ValueError("Invalid renew payload")

    plan = parts[1]
    if plan not in PLAN_TO_MONTHS:
        raise ValueError("Invalid renewal plan")
    if not parts[2].isdigit():
        raise ValueError("Invalid subscription id")
    sub_id = int(parts[2])
    if sub_id <= 0:
        raise ValueError("Invalid subscription id")

    discount = 0
    bonus_used = 0
    for part in parts[3:]:
        if part.startswith("d") and part[1:].isdigit():
            discount = int(part[1:])
        elif part.startswith("b") and part[1:].isdigit():
            bonus_used = int(part[1:])
        else:
            raise ValueError("Invalid renewal payload option")

    calculate_invoice_price(plan, discount, bonus_used)
    return plan, sub_id, discount, bonus_used


def get_base_price(plan: str) -> int:
    if plan not in PLAN_PRICES:
        raise ValueError(f"Unknown plan: {plan}")
    return int(PLAN_PRICES[plan])


def build_provider_data(receipt_desc: str, price_rub: int) -> dict:
    return {
        "receipt": {
            "items": [
                {
                    "description": receipt_desc,
                    "quantity": "1.00",
                    "amount": {"value": f"{int(price_rub)}.00", "currency": "RUB"},
                    "vat_code": 1,
                }
            ]
        }
    }


def format_tariff_lines(discount_percent: int = 0) -> list[str]:
    lines: list[str] = []
    for plan in PLAN_ORDER:
        period = PLAN_PERIOD_LABELS[plan]
        fake = PLAN_FAKE_PRICES[plan]
        base = PLAN_PRICES[plan]
        final = apply_discount(base, discount_percent)

        if discount_percent > 0 and final != base:
            lines.append(
                f"📅 <b>{period}</b> — <s>{base} ₽</s>   <b>{final} ₽</b>  <i>(−{discount_percent}%)</i>"
            )
        else:
            lines.append(f"📅 <b>{period}</b> — <s>{fake} ₽</s>   <b>{base} ₽</b>")
    return lines


async def get_user_payments_count(session, tg_id: int) -> int:
    res = await session.execute(select(func.count(Payments.id)).where(Payments.tg_id == tg_id))
    return int(res.scalar() or 0)


async def get_active_discount_percent(session, tg_id: int) -> int:
    q = (
        select(PromoRedemption, PromoCode)
        .join(PromoCode, PromoCode.id == PromoRedemption.promo_id)
        .where(
            PromoRedemption.user_tg_id == tg_id,
            PromoRedemption.is_activated.is_(True),
            PromoCode.is_active.is_(True),
            PromoCode.expires_at > utc_now_naive(),
        )
        .order_by(PromoRedemption.id.desc())
    )

    has_payments: bool | None = None
    for redemption, promo in (await session.execute(q)).all():
        if redemption.uses_count >= int(promo.max_uses_per_user or 0):
            continue
        if promo.first_purchase_only:
            if has_payments is None:
                has_payments = await get_user_payments_count(session, tg_id) > 0
            if has_payments:
                continue
        discount = int(promo.discount_percent or 0)
        if 0 < discount <= MAX_DISCOUNT_PERCENT:
            return discount
    return 0


async def mark_promo_used_if_applicable(session, tg_id: int, is_first_payment: bool) -> None:
    q = (
        select(PromoRedemption, PromoCode)
        .join(PromoCode, PromoCode.id == PromoRedemption.promo_id)
        .where(
            PromoRedemption.user_tg_id == tg_id,
            PromoRedemption.is_activated.is_(True),
            PromoCode.is_active.is_(True),
            PromoCode.expires_at > utc_now_naive(),
        )
        .order_by(PromoRedemption.id.desc())
    )
    for redemption, promo in (await session.execute(q)).all():
        if redemption.uses_count >= int(promo.max_uses_per_user or 0):
            continue
        if promo.first_purchase_only and not is_first_payment:
            continue
        redemption.uses_count += 1
        redemption.is_activated = (
            redemption.uses_count < int(promo.max_uses_per_user or 0)
        )
        redemption.last_used_at = utc_now_naive()
        return


async def get_user_bonus_balance(session, tg_id: int) -> int:
    ures = await session.execute(select(User).where(User.tg_id == tg_id))
    user = ures.scalar_one_or_none()
    if not user:
        return 0
    return int(getattr(user, "bonus_balance", 0) or 0)
