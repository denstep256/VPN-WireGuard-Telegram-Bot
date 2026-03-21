from datetime import datetime, timedelta

from app.database.models import async_session, Referral, PromoCode, PromoRedemption
from app.database.models import User
from sqlalchemy import select
import secrets
import string


async def set_user_start(tg_id, username, first_name, date_add, start_arg: str | None = None):
    promo_text_to_send = None

    async with async_session() as session:
        # user
        res = await session.execute(select(User).where(User.tg_id == tg_id))
        user = res.scalar_one_or_none()

        is_new_user = False
        if not user:
            is_new_user = True
            user = User(
                tg_id=tg_id,
                username=username or "unknown",
                first_name=first_name or "unknown",
                date=str(date_add),
                bonus_balance=0,  # если добавишь колонку
            )
            session.add(user)
            await session.flush()

        # referral row (ref_code)
        ref_res = await session.execute(select(Referral).where(Referral.user_tg_id == tg_id))
        ref_row = ref_res.scalar_one_or_none()

        if not ref_row:
            ref_code = await generate_unique_ref_code(session)
            ref_row = Referral(user_tg_id=tg_id, ref_code=ref_code)
            session.add(ref_row)
            await session.flush()

        # пришёл по рефке (только новый юзер)
        if is_new_user and start_arg and start_arg.startswith("ref_"):
            inviter_code = start_arg.replace("ref_", "", 1).strip()

            inviter_ref_res = await session.execute(select(Referral).where(Referral.ref_code == inviter_code))
            inviter_ref = inviter_ref_res.scalar_one_or_none()

            if inviter_ref and inviter_ref.user_tg_id != tg_id:
                ref_row.invited_by_tg_id = inviter_ref.user_tg_id

                # 1) создать персональный промокод (на будущее: owner_tg_id != None)
                promo_code = await generate_unique_promo_code(session, prefix="REF10-")
                promo_expires_at = datetime.utcnow() + timedelta(days=365)
                promo = PromoCode(
                    code=promo_code,
                    discount_percent=10,
                    owner_tg_id=tg_id,
                    is_active=True,
                    first_purchase_only=True,
                    max_uses_per_user=1,
                    expires_at=promo_expires_at,
                )
                session.add(promo)
                await session.flush()

                # 2) создать redemption (активирован)
                redemption = PromoRedemption(
                    user_tg_id=tg_id,
                    promo_id=promo.id,
                    is_activated=True,
                    uses_count=0,
                )
                session.add(redemption)

                promo_text_to_send = (
                    "🎟 <b>Промокод для вас</b>\n\n"
                    "Вы пришли по приглашению — держите скидку <b>10%</b> на <b>первую оплату</b>.\n\n"
                    f"Ваш промокод: <code>{promo_code}</code>\n\n"
                    f"Действует до: <b>{promo_expires_at.date().isoformat()}</b>\n\n"
                    "Нажмите кнопку <b>Промокод</b> и введите его перед покупкой."
                )

        await session.commit()

    return promo_text_to_send

REF_ALPHABET = string.ascii_uppercase + string.digits
PROMO_ALPHABET = string.ascii_uppercase + string.digits

def _gen_code(alpha: str, length: int) -> str:
    return "".join(secrets.choice(alpha) for _ in range(length))

async def generate_unique_ref_code(session, length: int = 10) -> str:
    while True:
        code = _gen_code(REF_ALPHABET, length)
        exists = await session.execute(select(Referral.id).where(Referral.ref_code == code))
        if exists.scalar_one_or_none() is None:
            return code

async def generate_unique_promo_code(session, length: int = 10, prefix: str = "REF10-") -> str:
    while True:
        code = prefix + _gen_code(PROMO_ALPHABET, length)
        exists = await session.execute(select(PromoCode.id).where(PromoCode.code == code))
        if exists.scalar_one_or_none() is None:
            return code
