import json
from datetime import datetime
from html import escape

from aiogram.types import Message
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram import Router, F

import app.users.keyboard as kb
import app.database.requests as rq
import config
from app.addons.button_text import BUTTON_TEXTS
from config import ADMIN_ID

router = Router()


with open("app/addons/texts.json", encoding="utf-8") as file_handler:
    text_mess = json.load(file_handler)
    texts_for_bot = text_mess


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    start_arg = None
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) > 1:
        start_arg = parts[1].strip()

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

        await message.answer(promo_code_text, parse_mode="HTML")

    if message.from_user.id == int(ADMIN_ID):

        await message.answer('Вы авторизовались как администратор')

@router.message(F.text == 'Помощь 🆘')
async def help_main_button(message: Message):

    await message.answer(texts_for_bot["help_message"], parse_mode='HTML', reply_markup=kb.help_kb)

@router.message(F.text == 'О VPN ℹ️')
async def help_main_button(message: Message):
    await message.answer(texts_for_bot["about_message"], parse_mode='HTML')

@router.message(F.text == 'Назад ↩️')
async def help_main_button(message: Message, state: FSMContext):
    await state.clear()
    if message.from_user.id == int(ADMIN_ID):
        await message.answer('Вы вернулись в главное меню', reply_markup=kb.get_main_keyboard(message.from_user.id))
    else:
        await message.answer('Вы вернулись в главное меню', reply_markup=kb.get_main_keyboard(message.from_user.id))

@router.message(F.text == BUTTON_TEXTS["how_connect"])
async def send_connection_instructions(message: Message):
    instructions = (
        ("VLESS", config.VPN_INSTRUCTION_VLESS),
        ("WireGuard для iPhone", config.VPN_INSTRUCTION_IOS_URL),
        ("WireGuard для Android", config.VPN_INSTRUCTION_ANDROID_URL),
    )
    text = "\n".join([
        "Чтобы настроить VPN, откройте инструкцию для вашего подключения.",
        "",
        *(f'<a href="{escape(url)}">{label}</a>' for label, url in instructions),
    ])
    await message.answer(
        text,
        parse_mode="HTML",
        reply_markup=kb.get_main_keyboard(message.from_user.id),
        disable_web_page_preview=True,
    )
