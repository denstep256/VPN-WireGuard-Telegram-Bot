from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from sqlalchemy import select

import app.users.keyboard as kb
from app.addons.button_text import BUTTON_TEXTS
from app.addons.utilits import build_tariff_caption
from app.database.models import async_session, Server
from app.payments.pricing import get_active_discount_percent

user_buy_router = Router()


@user_buy_router.message(F.text == BUTTON_TEXTS["products"])
async def help_main_button(message: Message):
    async with async_session() as session:
        keyboard = await kb.get_servers_keyboard(session)
        await message.answer(
            "🌍 <b>Выберите сервер</b>",
            reply_markup=keyboard,
            parse_mode="HTML"
        )

@user_buy_router.callback_query(F.data.startswith("srv|"))
async def handle_server_selection(callback: CallbackQuery):
    parts = callback.data.split("|")
    if len(parts) != 3:
        await callback.answer("❌ Некорректный формат выбора сервера.", show_alert=True)
        return

    region, region_id_str = parts[1], parts[2]
    if not region_id_str.isdigit():
        await callback.answer("⚠️ Неверный ID региона.", show_alert=True)
        return
    region_id = int(region_id_str)

    # Ищем сервер по region + region_id (и is_active=True)
    async with async_session() as session:
        result = await session.execute(
            select(Server).where(
                Server.region == region,
                Server.region_id == region_id,
                Server.is_active.is_(True)
            )
        )
        server = result.scalar_one_or_none()

        if not server:
            await callback.answer("❌ Сервер не найден или недоступен.", show_alert=True)
            return

        discount_percent = await get_active_discount_percent(session, callback.from_user.id)

    caption_text = build_tariff_caption(
        server_region=server.region,
        server_region_id=server.region_id,
        discount_percent=discount_percent,
    )

    await callback.message.edit_text(
        text=caption_text,
        parse_mode="HTML",
        reply_markup=kb.get_buy_kb(server.region, server.region_id)
    )

    await callback.answer()


@user_buy_router.callback_query(F.data == "no_servers")
async def handle_no_servers(callback: CallbackQuery):
    await callback.answer("Сейчас нет доступных серверов.", show_alert=True)
