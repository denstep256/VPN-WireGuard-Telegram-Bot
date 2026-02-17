import json
from datetime import datetime

from aiogram.types import Message, FSInputFile, CallbackQuery, InputMediaPhoto, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart
from sqlalchemy import select
from aiogram import Router, F

import app.users.keyboard as kb
import app.admin.admin_keyboard as admin_kb
import app.database.requests as rq
from app.database.models import TestPeriod, Subscribers, async_session, Server
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
    await message.answer(texts_for_bot['iphone_message'], reply_markup=kb.accept_kb)

@router.message(F.text == 'Android 📱')
async def help_main_button(message: Message):
    await message.answer(texts_for_bot['android_message'], reply_markup=kb.accept_kb)

@router.message(F.text == 'Скачал✅')
async def help_main_button(message: Message):
    # Сообщение с inline кнопками
    await message.answer(
        texts_for_bot['download_message'],
        reply_markup=kb.download_kb
    )
    # Отдельное сообщение с основной клавиатурой
    await message.answer(
        "Вы вернулись в главное меню",
        reply_markup=kb.main
    )