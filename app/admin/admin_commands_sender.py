from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

from sqlalchemy import select

import app.admin.admin_keyboard as kb
from app.admin.admin_keyboard import preview_kb
from app.database.models import async_session, User
from app.users.handlers import texts_for_bot
from config import ADMIN_ID

admin_command_router = Router()

class BroadcastState(StatesGroup):
    confirmation = State()
    choosing_type = State()
    waiting_for_photo = State()
    waiting_for_text = State()
    preview_message = State()

@admin_command_router.message(F.text == 'Рассылка')
async def choose_broadcast_type(message: Message, state: FSMContext):
    if message.from_user.id == int(ADMIN_ID):
        await message.answer('Выберите тип рассылки:', reply_markup=kb.send_kb)  # Предполагаем, что у вас есть клавиатура для выбора
        await state.set_state(BroadcastState.choosing_type)
    else:
        await message.answer('У вас нет доступа')

@admin_command_router.message(BroadcastState.choosing_type)
async def handle_broadcast_choice(message: Message, state: FSMContext):
    if message.text == 'С фото':
        await message.answer('Пожалуйста, отправьте фото для рассылки:')
        await state.set_state(BroadcastState.waiting_for_photo)
    elif message.text == 'Без фото':
        await message.answer(texts_for_bot["admin_commands_sender"])
        await state.set_state(BroadcastState.waiting_for_text)

@admin_command_router.message(BroadcastState.waiting_for_photo)
async def receive_photo(message: Message, state: FSMContext):
    if message.photo:
        await state.update_data(photo=message.photo[-1].file_id)  # Сохраняем самое высокое качество
        await message.answer(texts_for_bot["admin_commands_sender"])
        await state.set_state(BroadcastState.waiting_for_text)
    else:
        await message.answer('Пожалуйста, отправьте фото.')


@admin_command_router.message(BroadcastState.waiting_for_text)
async def prepare_broadcast_message(message: Message, state: FSMContext):
    if message.from_user.id == int(ADMIN_ID):
        broadcast_text = message.text
        data = await state.get_data()
        photo_id = data.get('photo')

        # Предоставляем пользователю возможность подтвердить рассылку
        confirmation_text = "Вы уверены, что хотите отправить следующее сообщение:\n\n"

        # Если фото есть, отправляем его как предварительный просмотр
        if photo_id:
            await message.answer_photo(photo=photo_id, caption=broadcast_text, parse_mode="HTML")  # Предварительный просмотр
            # confirmation_text += f"[Фото будет прикреплено]\n\n{broadcast_text}"
        else:
            confirmation_text += broadcast_text

        # Сохраняем текст для дальнейшего использования
        await state.update_data(text=broadcast_text)

        # Запрос на подтверждение
        await message.answer(confirmation_text,
                             reply_markup=preview_kb, parse_mode="HTML")  # Предполагается, что у вас есть клавиатура для подтверждения
        await state.set_state(BroadcastState.confirmation)
    else:
        await message.answer('У вас нет доступа')

@admin_command_router.callback_query(F.data == "confirm_broadcast")
async def start_broadcast(callback: CallbackQuery, state: FSMContext, bot: Bot):
    await callback.answer()  # Убедитесь, что вы отвечаете на колбек
    data = await state.get_data()
    photo_id = data.get('photo')
    broadcast_text = data.get('text')  # Получаем текст из состояния

    async with async_session() as session:
        result = await session.execute(select(User.tg_id))
        users = result.scalars().all()

    successful_sends = 0
    failed_sends = 0

    for user_id in users:
        try:
            if photo_id:
                await bot.send_photo(chat_id=user_id, photo=photo_id, caption=broadcast_text, parse_mode="HTML")
            else:
                await bot.send_message(chat_id=user_id, text=broadcast_text, parse_mode="HTML")
            successful_sends += 1
        except Exception:
            failed_sends += 1  # Обработка ошибок

    await callback.message.answer(f'Рассылка завершена. Успешных отправок: {successful_sends}, неудачных: {failed_sends}', reply_markup=kb.admin_panel)
    await state.clear()

@admin_command_router.callback_query(F.data == 'cancel_broadcast')
async def cancel_broadcast(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("Рассылка отменена.", reply_markup=kb.admin_panel)
    await state.clear()
