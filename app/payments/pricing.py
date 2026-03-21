from __future__ import annotations

from datetime import datetime

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


def apply_discount(price_rub: int, discount_percent: int) -> int:
    if discount_percent <= 0:
        return int(price_rub)
    return int(round(int(price_rub) * (100 - int(discount_percent)) / 100))


def calc_bonus_to_use(price_after_discount: int, user_bonus_balance: int) -> int:
    if int(price_after_discount) <= MIN_PAY_RUB:
        return 0
    max_bonus_allowed = int(price_after_discount) - MIN_PAY_RUB
    return max(0, min(int(user_bonus_balance or 0), max_bonus_allowed))


def build_buy_payload(base_plan: str, region: str, region_id: int, discount: int, bonus_used: int) -> str:
    return f"{base_plan}|{region}|{region_id}|d{discount}|b{bonus_used}"


def parse_buy_payload(payload: str) -> tuple[str, str, int, int, int]:
    parts = (payload or "").split("|")
    if len(parts) < 3:
        raise ValueError("Invalid payload")

    base_plan = parts[0]
    region = parts[1]
    if not parts[2].isdigit():
        raise ValueError("Invalid region id")
    region_id = int(parts[2])

    discount = 0
    bonus_used = 0
    for part in parts[3:]:
        if part.startswith("d") and part[1:].isdigit():
            discount = int(part[1:])
        elif part.startswith("b") and part[1:].isdigit():
            bonus_used = int(part[1:])

    return base_plan, region, region_id, discount, bonus_used


def build_renew_payload(plan: str, sub_id: int, discount: int, bonus_used: int) -> str:
    return f"renew|{plan}|{sub_id}|d{discount}|b{bonus_used}"


def parse_renew_payload(payload: str) -> tuple[str, int, int, int]:
    parts = (payload or "").split("|")
    if len(parts) < 3 or parts[0] != "renew":
        raise ValueError("Invalid renew payload")

    plan = parts[1]
    if not parts[2].isdigit():
        raise ValueError("Invalid subscription id")
    sub_id = int(parts[2])

    discount = 0
    bonus_used = 0
    for part in parts[3:]:
        if part.startswith("d") and part[1:].isdigit():
            discount = int(part[1:])
        elif part.startswith("b") and part[1:].isdigit():
            bonus_used = int(part[1:])

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
            PromoRedemption.is_activated == True,  # noqa: E712
            PromoCode.is_active == True,  # noqa: E712
            PromoCode.expires_at > datetime.utcnow(),
        )
        .order_by(PromoRedemption.id.desc())
        .limit(1)
    )

    row = (await session.execute(q)).first()
    if not row:
        return 0

    redemption, promo = row

    if redemption.uses_count >= int(promo.max_uses_per_user or 0):
        return 0

    if promo.first_purchase_only:
        if await get_user_payments_count(session, tg_id) > 0:
            return 0

    return int(promo.discount_percent or 0)


async def mark_promo_used_if_applicable(session, tg_id: int, is_first_payment: bool) -> None:
    q = (
        select(PromoRedemption, PromoCode)
        .join(PromoCode, PromoCode.id == PromoRedemption.promo_id)
        .where(
            PromoRedemption.user_tg_id == tg_id,
            PromoRedemption.is_activated == True,  # noqa: E712
            PromoCode.is_active == True,  # noqa: E712
            PromoCode.expires_at > datetime.utcnow(),
        )
        .order_by(PromoRedemption.id.desc())
        .limit(1)
    )
    row = (await session.execute(q)).first()
    if not row:
        return

    redemption, promo = row

    if redemption.uses_count >= int(promo.max_uses_per_user or 0):
        return
    if promo.first_purchase_only and not is_first_payment:
        return

    redemption.uses_count += 1
    redemption.is_activated = False
    redemption.last_used_at = datetime.utcnow()


async def get_user_bonus_balance(session, tg_id: int) -> int:
    ures = await session.execute(select(User).where(User.tg_id == tg_id))
    user = ures.scalar_one_or_none()
    if not user:
        return 0
    return int(getattr(user, "bonus_balance", 0) or 0)
