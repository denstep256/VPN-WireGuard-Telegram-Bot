from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from app.addons.button_text import BUTTON_TEXTS
from app.addons.utilits import build_tariff_caption
from app.database.models import async_session
from app.payments.pricing import get_active_discount_percent
from app.users.keyboard import get_buy_kb

user_buy_router = Router()


async def send_tariffs(message: Message, tg_id: int) -> None:
    async with async_session() as session:
        discount = await get_active_discount_percent(session, tg_id)
    await message.answer(build_tariff_caption(discount), reply_markup=get_buy_kb(), parse_mode="HTML")


@user_buy_router.message(F.text == BUTTON_TEXTS["products"])
async def show_tariffs(message: Message):
    await send_tariffs(message, message.from_user.id)


@user_buy_router.callback_query(F.data.startswith("proto|") | F.data.startswith("srv|"))
async def show_tariffs_from_old_keyboard(call: CallbackQuery):
    await send_tariffs(call.message, call.from_user.id)
    await call.answer()
