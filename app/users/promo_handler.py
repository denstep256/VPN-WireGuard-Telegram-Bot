from aiogram import F, Router
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy import select
import app.users.keyboard as kb

from app.addons.button_text import BUTTON_TEXTS
from app.database.models import async_session, PromoCode, PromoRedemption, Payments

promocode_router = Router()

class PromoStates(StatesGroup):
    waiting_code = State()

@promocode_router.message(F.text == BUTTON_TEXTS["promocode"])
async def promo_start(message: Message, state: FSMContext):
    await state.set_state(PromoStates.waiting_code)
    await message.answer("🎟 Введите промокод, и я сразу пересчитаю стоимость тарифа.", reply_markup=kb.back_kb)

@promocode_router.message(PromoStates.waiting_code)
async def promo_entered(message: Message, state: FSMContext):
    code = (message.text or "").strip().upper()
    tg_id = message.from_user.id

    async with async_session() as session:
        pres = await session.execute(select(PromoCode).where(PromoCode.code == code))
        promo = pres.scalar_one_or_none()

        if not promo or not promo.is_active:
            await message.answer("❌ Промокод не найден или отключён.", reply_markup=kb.get_main_keyboard(message.from_user.id))
            await state.clear()
            return

        # персональный промокод
        if promo.owner_tg_id is not None and promo.owner_tg_id != tg_id:
            await message.answer("⚠️ Этот промокод предназначен для другого пользователя.", reply_markup=kb.get_main_keyboard(message.from_user.id))
            await state.clear()
            return

        if promo.first_purchase_only:
            pay_res = await session.execute(
                select(Payments.id).where(Payments.tg_id == tg_id).limit(1)
            )
            if pay_res.scalar_one_or_none() is not None:
                await message.answer(
                    "⚠️ Этот промокод действует только на первую оплату.",
                    reply_markup=kb.get_main_keyboard(message.from_user.id),
                )
                await state.clear()
                return

        rres = await session.execute(
            select(PromoRedemption).where(
                PromoRedemption.user_tg_id == tg_id,
                PromoRedemption.promo_id == promo.id
            )
        )
        redemption = rres.scalar_one_or_none()

        if redemption and redemption.uses_count >= promo.max_uses_per_user:
            await message.answer("⚠️ Этот промокод уже был использован максимальное число раз.", reply_markup=kb.get_main_keyboard(message.from_user.id))
            await state.clear()
            return

        if not redemption:
            redemption = PromoRedemption(
                user_tg_id=tg_id,
                promo_id=promo.id,
                is_activated=True,
                uses_count=0
            )
            session.add(redemption)
        else:
            redemption.is_activated = True

        await session.commit()

    await message.answer(
        "✅ Промокод активирован. Новая цена уже будет показана в выборе тарифа.",
        reply_markup=kb.get_main_keyboard(message.from_user.id),
    )
    await state.clear()
