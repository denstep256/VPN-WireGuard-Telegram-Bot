from aiogram import F, Router, Bot
from aiogram.types import Message
from sqlalchemy import select

from app.addons.button_text import BUTTON_TEXTS
from app.database.models import async_session, User, Referral
from app.database.requests import generate_unique_ref_code

invite_router = Router()

@invite_router.message(F.text == BUTTON_TEXTS["invite_friend"])
async def invite_friend(message: Message, bot: Bot):
    tg_id = message.from_user.id

    async with async_session() as session:
        # баланс
        ures = await session.execute(select(User).where(User.tg_id == tg_id))
        user = ures.scalar_one()

        # рефкод
        rres = await session.execute(select(Referral).where(Referral.user_tg_id == tg_id))
        ref_row = rres.scalar_one_or_none()
        if not ref_row:
            ref_code = await generate_unique_ref_code(session)
            ref_row = Referral(user_tg_id=tg_id, ref_code=ref_code)
            session.add(ref_row)
            await session.commit()

    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start=ref_{ref_row.ref_code}"

    text = (
        f"💰 <b>Ваш бонусный баланс:</b> <b>{user.bonus_balance} ₽</b>\n\n"
        "🎁 <b>Реферальная акция</b>\n"
        "Пригласи друга — после его первой оплаты тебе начислится <b>100 ₽</b> на бонусный баланс.\n"
        "Друг получит <b>персональный промокод</b> на <b>скидку 10%</b> на первую оплату.\n\n"
        f"🔗 <b>Твоя ссылка:</b>\n<code>{link}</code>"
    )
    await message.answer(text, parse_mode="HTML")