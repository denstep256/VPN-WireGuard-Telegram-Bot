from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, FSInputFile, \
    InputMediaPhoto
from sqlalchemy import select

import app.users.keyboard as kb
from app.addons.button_text import BUTTON_TEXTS
from app.database.models import async_session, Server

from config import one_mounth_fake_price, one_mounth_price, twelve_mounth_fake_price, six_mounth_price, \
    twelve_mounth_price, six_mounth_fake_price

user_buy_router = Router()


@user_buy_router.message(F.text == BUTTON_TEXTS["products"])
async def help_main_button(message: Message):
    async with async_session() as session:
        keyboard = await kb.get_servers_keyboard(session)
        await message.answer(
            "<b>Выберите сервер</b>",
            reply_markup=keyboard,
            parse_mode="HTML"
        )

@user_buy_router.callback_query(F.data.contains("srv|"))
async def handle_server_selection(callback: CallbackQuery):
    parts = callback.data.split("|")
    if len(parts) < 3:
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
                Server.is_active == True
            )
        )
        server = result.scalar_one_or_none()

        if not server:
            await callback.answer("❌ Сервер не найден или недоступен.", show_alert=True)
            return

    # Формируем caption
    caption_text = (
        "🛡️ <b>Wireguard VPN</b>\n\n"
        f"📍 <b>Сервер:</b> {server.region} №{server.region_id}\n\n"
        f"📅 <b>1 мес.</b> — <s>{one_mounth_fake_price} руб.</s>   <b>{one_mounth_price} руб.</b>\n"
        f"📅 <b>6 мес.</b> — <s>{six_mounth_fake_price} руб.</s>   <b>{six_mounth_price} руб.</b>\n"
        f"📅 <b>12 мес.</b> — <s>{twelve_mounth_fake_price} руб.</s>   <b>{twelve_mounth_price} руб.</b>"
    )

    photo = FSInputFile("app/Pictures/WireGuard_ logo.jpeg")
    await callback.message.edit_media(
        media=InputMediaPhoto(media=photo),
        reply_markup=kb.get_buy_kb(server.region, server.region_id)
    )
    await callback.message.edit_caption(
        caption=caption_text,
        parse_mode="HTML",
        reply_markup=kb.get_buy_kb(server.region, server.region_id)
    )

    await callback.answer()