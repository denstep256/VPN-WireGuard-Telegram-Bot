from aiogram import F, Router
from aiogram.types import CallbackQuery, FSInputFile, Message
from sqlalchemy import select

import app.users.keyboard as kb
from app.addons.button_text import BUTTON_TEXTS
from app.addons.utilits import build_tariff_caption
from app.database.models import Server, async_session
from app.payments.pricing import get_active_discount_percent
from app.vpn.provisioning import (
    PROTOCOL_WIREGUARD,
    get_protocol_label,
    server_protocol_filter,
)

user_buy_router = Router()


@user_buy_router.message(F.text == BUTTON_TEXTS["products"])
async def help_main_button(message: Message):
    await message.answer(
        "🛡️ VLESS — гибкая настройка и хорошая маскировка трафика.\n"
        "⚡ WireGuard — проще в подключении и обычно быстрее.\n\n"
        "Выберите подходящий протокол:",
        reply_markup=kb.get_protocols_keyboard(),
        parse_mode="HTML",
    )


@user_buy_router.callback_query(F.data.startswith("proto|"))
async def handle_protocol_selection(callback: CallbackQuery):
    parts = callback.data.split("|")
    if len(parts) != 2:
        await callback.answer("❌ Некорректный формат выбора протокола.", show_alert=True)
        return
    protocol = parts[1]

    async with async_session() as session:
        keyboard = await kb.get_servers_keyboard(session, protocol=protocol)
    await callback.message.answer(
        f"🌍 <b>Выберите сервер {get_protocol_label(protocol)}</b>",
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    await callback.answer()


@user_buy_router.callback_query(F.data.contains("srv|"))
async def handle_server_selection(callback: CallbackQuery):
    parts = callback.data.split("|")
    if len(parts) == 4:
        protocol, region, region_id_str = parts[1], parts[2], parts[3]
    elif len(parts) >= 3:
        protocol, region, region_id_str = PROTOCOL_WIREGUARD, parts[1], parts[2]
    else:
        await callback.answer("❌ Некорректный формат выбора сервера.", show_alert=True)
        return

    if not region_id_str.isdigit():
        await callback.answer("⚠️ Неверный ID региона.", show_alert=True)
        return
    region_id = int(region_id_str)

    async with async_session() as session:
        result = await session.execute(
            select(Server).where(
                Server.region == region,
                Server.region_id == region_id,
                Server.is_active == True,  # noqa: E712
                server_protocol_filter(protocol),
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
        protocol=protocol,
    )

    photo = FSInputFile("app/Pictures/WireGuard_ logo.jpeg")
    await callback.message.answer_photo(
        photo=photo,
        caption=caption_text,
        parse_mode="HTML",
        reply_markup=kb.get_buy_kb(server.region, server.region_id, protocol=protocol),
    )

    await callback.answer()
