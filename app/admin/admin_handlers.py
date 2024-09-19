from aiogram.types import Message

from aiogram import Router, F
from sqlalchemy import select, func

import app.admin.admin_keyboard as kb
from config import ADMIN_ID
from app.database.models import async_session, TestPeriod
from app.database.models import Subscribers

admin_router = Router()


@admin_router.message(F.text == 'Админ')
async def admin_panel_button(message: Message):
    if message.from_user.id == int(ADMIN_ID):
        await message.answer('Вы вошли в админ-панель', reply_markup=kb.admin_panel)
    else:
        await message.answer('У вас нет доступа')

@admin_router.message(F.text == 'Назад (Админ)')
async def help_main_button(message: Message):
    if message.from_user.id == int(ADMIN_ID):
        await message.answer('Вы вернулись в главное меню', reply_markup=kb.main_admin)
    else:
        await message.answer('У вас нет доступа')


@admin_router.message(F.text == 'Пользователи с подпиской')
async def users_with_subscribe_admin(message: Message):
    if message.from_user.id == int(ADMIN_ID):
        async with async_session() as session:
            # Запрос для подсчета количества активных подписчиков
            result = await session.scalar(
                select(func.count()).select_from(Subscribers)
            )

            # Отправляем сообщение с количеством пользователей
            await message.answer(f'Количество пользователей с активной подпиской: {result}', reply_markup=kb.admin_panel)
    else:
        await message.answer('У вас нет доступа')

@admin_router.message(F.text == 'Пользователи с пробным периодом')
async def users_with_trial_period_admin(message: Message):
    if message.from_user.id == int(ADMIN_ID):
        async with async_session() as session:
            # Запрос для подсчета количества активных подписчиков
            result = await session.scalar(
                select(func.count()).select_from(TestPeriod)
            )

            # Отправляем сообщение с количеством пользователей
            await message.answer(f'Количество пользователей с активной пробной подпиской: {result}',
                                 reply_markup=kb.admin_panel)
    else:
        await message.answer('У вас нет доступа')