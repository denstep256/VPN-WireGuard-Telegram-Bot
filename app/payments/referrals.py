import logging

from aiogram import Bot
from sqlalchemy import select

from app.database.models import Referral, User


logger = logging.getLogger(__name__)


async def apply_referral_bonus_if_applicable(session, buyer_tg_id: int) -> int | None:
    ref_result = await session.execute(
        select(Referral).where(Referral.user_tg_id == buyer_tg_id)
    )
    referral = ref_result.scalar_one_or_none()
    if not referral or not referral.invited_by_tg_id or referral.inviter_rewarded:
        return None

    inviter_tg_id = int(referral.invited_by_tg_id)
    inviter_result = await session.execute(
        select(User).where(User.tg_id == inviter_tg_id)
    )
    inviter = inviter_result.scalar_one_or_none()
    if not inviter:
        logger.error(
            "Referral inviter does not exist: buyer_tg_id=%s inviter_tg_id=%s",
            buyer_tg_id,
            inviter_tg_id,
        )
        return None

    inviter.bonus_balance = int(inviter.bonus_balance or 0) + 100
    referral.inviter_rewarded = True
    return inviter_tg_id


async def notify_referral_bonus(bot: Bot, buyer_tg_id: int, inviter_tg_id: int) -> None:
    try:
        await bot.send_message(
            inviter_tg_id,
            "🎉 Ваш друг оформил первую подписку!\n"
            "Вам начислено <b>100 ₽</b> на бонусный баланс.",
            parse_mode="HTML",
        )
    except Exception:
        logger.exception(
            "Ошибка отправки уведомления рефералу: buyer_tg_id=%s inviter_tg_id=%s",
            buyer_tg_id,
            inviter_tg_id,
        )
