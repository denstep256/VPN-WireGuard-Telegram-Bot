import json
from datetime import datetime

from aiogram.types import Message, FSInputFile
from aiogram.filters import CommandStart
from aiogram import Router, F
from sqlalchemy import select

import app.users.keyboard as kb
import app.admin.admin_keyboard as admin_kb
import app.database.requests as rq
from app.database.models import TestPeriod, Subscribers, async_session
from config import ADMIN_ID

router = Router()

with open("app/addons/texts.json", encoding="utf-8") as file_handler:
    text_mess = json.load(file_handler)
    texts_for_bot = text_mess

@router.message(CommandStart())
async def cmd_start(message: Message):
    await rq.set_user(message.from_user.id,
                      message.from_user.username,
                      message.from_user.first_name,
                      datetime.now())
    await message.answer(texts_for_bot["start_message"], parse_mode='HTML', reply_markup=kb.main)
    if message.from_user.id == int(ADMIN_ID):
        await message.answer('Вы авторизовались как администратор', reply_markup=admin_kb.main_admin)


@router.message(F.text == 'Помощь')
async def help_main_button(message: Message):
    await message.answer(texts_for_bot["help_message"], parse_mode='HTML', reply_markup=kb.help_kb)

@router.message(F.text == 'О VPN')
async def help_main_button(message: Message):
    await message.answer(texts_for_bot["about_message"], parse_mode='HTML')

@router.message(F.text == 'Проверить подписку')
@router.message(F.text == 'Проверить подписку')
async def check_subscribe_button(message: Message):
    tg_id = message.from_user.id

    async with async_session() as session:
        # Проверяем пользователя в таблице Subscribers
        subscriber = await session.scalar(
            select(Subscribers).where(Subscribers.tg_id == tg_id)
        )

        if subscriber:
            # Форматируем дату окончания подписки
            expiry_date = subscriber.expiry_date
            await message.answer(f"Ваша подписка активна до {expiry_date}", parse_mode='HTML')
            return

        # Если пользователя нет в Subscribers, проверяем в TestPeriod
        test_period_user = await session.scalar(
            select(TestPeriod).where(TestPeriod.tg_id == tg_id)
        )

        if test_period_user:
            # Форматируем дату окончания пробного периода
            expiry_date = test_period_user.expiry_date
            await message.answer(f"Ваша пробная подписка активна до {expiry_date}", parse_mode='HTML')
            return

        # Если пользователя нет ни в одной из таблиц
        await message.answer("У вас нет активной подписки", parse_mode='HTML')

@router.message(F.text == 'Купить')
async def help_main_button(message: Message):
    photo = FSInputFile("app/Pictures/WireGuard_ logo.jpeg")
    await message.answer_photo(photo, caption=texts_for_bot["wireguard_photo_message"],parse_mode='HTML',
                               reply_markup=kb.buy_kb)


@router.message(F.text == 'Назад')
async def help_main_button(message: Message):
    if message.from_user.id == int(ADMIN_ID):
        await message.answer('Вы вернулись в главное меню (Админ)', reply_markup=admin_kb.main_admin)
    else:
        await message.answer('Вы вернулись в главное меню', reply_markup=kb.main)

@router.message(F.text == 'Как подключить')
async def help_main_button(message: Message):
    await message.answer(texts_for_bot["how_to_connect"], reply_markup=kb.how_to_connect_kb)


@router.message(F.text == 'iPhone')
async def help_main_button(message: Message):
    await message.answer(texts_for_bot['iphone_message'], reply_markup=kb.iphone_kb)

@router.message(F.text == 'Android')
async def help_main_button(message: Message):
    await message.answer(texts_for_bot['android_message'], reply_markup=kb.android_kb)

@router.message(F.text == 'Скачал✅')
async def help_main_button(message: Message):
    await message.answer(texts_for_bot['download_message'], reply_markup=kb.download_kb)

# @router.message()
# async def default_answer(message: Message):
#     await message.answer('Я тебя не понимаю')


