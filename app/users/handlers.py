import json
import logging
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
logger = logging.getLogger(__name__)

with open("app/addons/texts.json", encoding="utf-8") as file_handler:
    text_mess = json.load(file_handler)
    texts_for_bot = text_mess


@router.message(CommandStart())
async def cmd_start(message: Message):
    start_arg = None
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) > 1:
        start_arg = parts[1].strip()
    logger.info("Command /start received: tg_id=%s start_arg=%s", message.from_user.id, start_arg)

    promo_code_text = await rq.set_user_start(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
        datetime.now(),
        start_arg=start_arg
    )

    await message.answer(texts_for_bot["start_message"], parse_mode='HTML', reply_markup=kb.get_main_keyboard(message.from_user.id))

    # если реферал — отправим ему промокод на первом /start (как ты хочешь)
    if promo_code_text:
        logger.info("Referral promo prepared for user: tg_id=%s", message.from_user.id)
        await message.answer(promo_code_text, parse_mode="HTML")

    if message.from_user.id == int(ADMIN_ID):
        logger.info("Admin entered main menu: tg_id=%s", message.from_user.id)
        await message.answer('Вы авторизовались как администратор')

@router.message(F.text == 'Помощь 🆘')
async def help_main_button(message: Message):
    logger.info("Help section opened: tg_id=%s", message.from_user.id)
    await message.answer(texts_for_bot["help_message"], parse_mode='HTML', reply_markup=kb.help_kb)

@router.message(F.text == 'О VPN ℹ️')
async def help_main_button(message: Message):
    logger.info("About section opened: tg_id=%s", message.from_user.id)
    await message.answer(texts_for_bot["about_message"], parse_mode='HTML')

@router.message(F.text == 'Назад ↩️')
async def help_main_button(message: Message):
    logger.info("Back to main menu pressed: tg_id=%s", message.from_user.id)
    if message.from_user.id == int(ADMIN_ID):
        await message.answer('Вы вернулись в главное меню', reply_markup=kb.get_main_keyboard(message.from_user.id))
    else:
        await message.answer('Вы вернулись в главное меню', reply_markup=kb.get_main_keyboard(message.from_user.id))

@router.message(F.text == 'Как подключить ⚙️')
async def help_main_button(message: Message):
    logger.info("How-to-connect opened: tg_id=%s", message.from_user.id)
    await message.answer(texts_for_bot["how_to_connect"], reply_markup=kb.how_to_connect_kb)


@router.message(F.text == 'iPhone 📱')
async def help_main_button(message: Message):
    logger.info("iPhone guide opened: tg_id=%s", message.from_user.id)
    await message.answer(texts_for_bot['iphone_message'], reply_markup=kb.accept_kb)

@router.message(F.text == 'Android 📱')
async def help_main_button(message: Message):
    logger.info("Android guide opened: tg_id=%s", message.from_user.id)
    await message.answer(texts_for_bot['android_message'], reply_markup=kb.accept_kb)

@router.message(F.text == 'Скачал✅')
async def help_main_button(message: Message):
    logger.info("Download confirmed: tg_id=%s", message.from_user.id)
    # Сообщение с inline кнопками
    await message.answer(
        texts_for_bot['download_message'],
        reply_markup=kb.download_kb
    )
    # Отдельное сообщение с основной клавиатурой
    await message.answer(
        "Вы вернулись в главное меню",
        reply_markup=kb.get_main_keyboard(message.from_user.id)
    )
