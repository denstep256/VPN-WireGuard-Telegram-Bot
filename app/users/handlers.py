import json

from aiogram.types import Message
from aiogram.filters import CommandStart
from aiogram import Router, F
from aiogram.fsm.context import FSMContext

import app.users.keyboard as kb
import app.database.requests as rq
from app.addons.button_text import BUTTON_TEXTS
from app.paths import TEXTS_PATH
from app.time_utils import utc_now_naive
from config import ADMIN_ID

router = Router()


with TEXTS_PATH.open(encoding="utf-8") as file_handler:
    text_mess = json.load(file_handler)
    texts_for_bot = text_mess


@router.message(CommandStart())
async def cmd_start(message: Message):
    start_arg = None
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) > 1:
        start_arg = parts[1].strip()

    promo_code_text = await rq.set_user_start(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
        utc_now_naive(),
        start_arg=start_arg
    )

    await message.answer(texts_for_bot["start_message"], parse_mode='HTML', reply_markup=kb.get_main_keyboard(message.from_user.id))

    # если реферал — отправим ему промокод на первом /start (как ты хочешь)
    if promo_code_text:

        await message.answer(promo_code_text, parse_mode="HTML")

    if message.from_user.id == int(ADMIN_ID):

        await message.answer('Вы авторизовались как администратор')

@router.message(F.text == BUTTON_TEXTS["help"])
async def show_help(message: Message):

    await message.answer(texts_for_bot["help_message"], parse_mode='HTML', reply_markup=kb.help_kb)

@router.message(F.text == BUTTON_TEXTS["about"])
async def show_about(message: Message):
    await message.answer(texts_for_bot["about_message"], parse_mode='HTML')

@router.message(F.text == BUTTON_TEXTS["back"])
async def back_to_main(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        'Вы вернулись в главное меню',
        reply_markup=kb.get_main_keyboard(message.from_user.id),
    )

@router.message(F.text == BUTTON_TEXTS["how_connect"])
async def show_connection_help(message: Message):
    await message.answer(texts_for_bot["how_to_connect"], reply_markup=kb.how_to_connect_kb)


@router.message(F.text == BUTTON_TEXTS["iphone"])
async def show_iphone_help(message: Message):
    await message.answer(texts_for_bot['iphone_message'], reply_markup=kb.accept_kb)

@router.message(F.text == BUTTON_TEXTS["android"])
async def show_android_help(message: Message):
    await message.answer(texts_for_bot['android_message'], reply_markup=kb.accept_kb)

@router.message(F.text == BUTTON_TEXTS["downloaded"])
async def confirm_download(message: Message):
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
