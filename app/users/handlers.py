import json
from datetime import datetime

from aiogram.types import Message, FSInputFile, CallbackQuery, InputMediaPhoto
from aiogram.filters import CommandStart
from aiogram import Router, F
from sqlalchemy import select
from app.database.models import async_session

import app.users.keyboard as kb
import app.admin.admin_keyboard as admin_kb
import app.database.requests as rq
from app.database.models import TestPeriod, Subscribers, async_session, engine, Server, async_main
from config import ADMIN_ID, one_mounth_fake_price, one_mounth_price, six_mounth_price, six_mounth_fake_price, twelve_mounth_price, twelve_mounth_fake_price

router = Router()

with open("app/addons/texts.json", encoding="utf-8") as file_handler:
    text_mess = json.load(file_handler)
    texts_for_bot = text_mess


@router.message(CommandStart())
async def cmd_start(message: Message):
    await rq.set_user_start(message.from_user.id,
                      message.from_user.username,
                      message.from_user.first_name,
                      datetime.now())
    await message.answer(texts_for_bot["start_message"], parse_mode='HTML', reply_markup=kb.main)
    if message.from_user.id == int(ADMIN_ID):
        await message.answer('Вы авторизовались как администратор', reply_markup=admin_kb.main_admin)

@router.message(F.text == 'Помощь 🆘')
async def help_main_button(message: Message):
    await message.answer(texts_for_bot["help_message"], parse_mode='HTML', reply_markup=kb.help_kb)

@router.message(F.text == 'О VPN ℹ️')
async def help_main_button(message: Message):
    await message.answer(texts_for_bot["about_message"], parse_mode='HTML')

@router.message(F.text == 'Проверить подписку ✅')
async def check_subscribe_button(message: Message):

    async with async_session() as session:
        tg_id = message.from_user.id
        # Проверяем пользователя в таблице Subscribers
        subscriber = await session.scalar(
            select(Subscribers).where(Subscribers.tg_id == tg_id)
        )

        if subscriber:
            # Форматируем дату окончания подписки
            expiry_date = subscriber.expiry_date
            await message.answer(f"✅ Ваша подписка активна до {expiry_date}.", parse_mode='HTML')

            query = select(Subscribers.file_name).filter_by(tg_id=tg_id)
            result = await session.execute(query)
            file_name = result.scalar_one_or_none()  # Получаем одно значение или None, если не найдено

            file_path = f"app/auth/{file_name}.conf"  # Укажи правильный путь к файлу
            document = FSInputFile(file_path)
            await message.answer_document(document)
            return

        # Если пользователя нет в Subscribers, проверяем в TestPeriod
        test_period_user = await session.scalar(
            select(TestPeriod).where(TestPeriod.tg_id == tg_id)
        )

        if test_period_user:
            # Форматируем дату окончания пробного периода
            expiry_date = test_period_user.expiry_date
            await message.answer(f"✅ Ваша пробная подписка активна до {expiry_date}.", parse_mode='HTML')

            query = select(TestPeriod.file_name).filter_by(tg_id=tg_id)
            result = await session.execute(query)
            file_name = result.scalar_one_or_none()  # Получаем одно значение или None, если не найдено

            file_path = f"app/auth/{file_name}.conf"  # Укажи правильный путь к файлу
            document = FSInputFile(file_path)
            await message.answer_document(document)
            return

        # Если пользователя нет ни в одной из таблиц
        await message.answer(texts_for_bot["not_active_subs"], parse_mode='HTML')


@router.callback_query(F.data.contains("-"))  # или F.data.regexp(r"^[^-]+-\d+$")
async def handle_server_selection(callback: CallbackQuery):
    data = callback.data

    # Разделяем по первому дефису (на случай, если region содержит дефисы)
    parts = data.split("-", 1)
    if len(parts) != 2:
        await callback.answer("❌ Некорректный формат выбора сервера.", show_alert=True)
        return

    region, region_id_str = parts

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
        server = result.scalar_one_or_none()  # аналог .first()

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
    # Редактируем текущее сообщение: сначала медиа, потом подпись
    await callback.message.edit_media(
        media=InputMediaPhoto(media=photo),
        reply_markup=kb.buy_kb
    )
    await callback.message.edit_caption(
        caption=caption_text,
        parse_mode="HTML",
        reply_markup=kb.buy_kb
    )

    await callback.answer()

@router.message(F.text == 'Купить 💳')
async def help_main_button(message: Message):
    async with async_session() as session:
        keyboard = await kb.get_servers_keyboard(session)
        await message.answer(
            "<b>Выберите сервер</b>",
            reply_markup=keyboard,
            parse_mode="HTML"
        )

@router.message(F.text == 'Назад ↩️')
async def help_main_button(message: Message):
    if message.from_user.id == int(ADMIN_ID):
        await message.answer('Вы вернулись в главное меню', reply_markup=admin_kb.main_admin)
    else:
        await message.answer('Вы вернулись в главное меню', reply_markup=kb.main)

@router.message(F.text == 'Как подключить ⚙️')
async def help_main_button(message: Message):
    await message.answer(texts_for_bot["how_to_connect"], reply_markup=kb.how_to_connect_kb)


@router.message(F.text == 'iPhone 📱')
async def help_main_button(message: Message):
    await message.answer(texts_for_bot['iphone_message'], reply_markup=kb.iphone_kb)

@router.message(F.text == 'Android 📱')
async def help_main_button(message: Message):
    await message.answer(texts_for_bot['android_message'], reply_markup=kb.android_kb)

@router.message(F.text == 'Скачал✅')
async def help_main_button(message: Message):
    await message.answer(texts_for_bot['download_message'], reply_markup=kb.download_kb)