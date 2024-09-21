from aiogram.types import Message


from aiogram import Router, F
from sqlalchemy import select, func

import app.admin.admin_keyboard as kb
from app.wg_api.wg_api import get_client_count_wg
from config import ADMIN_ID
from app.database.models import async_session, TestPeriod, User
from app.database.models import Subscribers

from aiogram.fsm.state import State, StatesGroup

class AdminState(StatesGroup):
    waiting_for_message = State()

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
            await message.answer(f'Количество пользователей с активной подпиской: {result}',
                                 reply_markup=kb.stat_kb)
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
                                 reply_markup=kb.stat_kb)
    else:
        await message.answer('У вас нет доступа')

@admin_router.message(F.text == 'Клиенты на сервере')
async def clients_on_server_wg(message: Message):
    if message.from_user.id == int(ADMIN_ID):
        result = await get_client_count_wg()
        await message.answer(f'Количество пользователей на сервере WG: {result}',
                                 reply_markup=kb.stat_kb)
    else:
        await message.answer('У вас нет доступа')

@admin_router.message(F.text == 'Пользователи в боте')
async def users_with_trial_period_admin(message: Message):
    if message.from_user.id == int(ADMIN_ID):
        async with async_session() as session:
            result = await session.execute(select(func.count()).select_from(User))
            users_count = result.scalar()  # Получаем количество пользователей

            await message.answer(f'Количество пользователей в users: {users_count}',
                                 reply_markup=kb.stat_kb)
    else:
        await message.answer('У вас нет доступа')


@admin_router.message(F.text == 'Рассылка')
async def admin_panel_button(message: Message):
    if message.from_user.id == int(ADMIN_ID):
        await message.answer('Выберите вариант рассылки', reply_markup=kb.send_kb)
    else:
        await message.answer('У вас нет доступа')

@admin_router.message(F.text == 'Статистика')
async def admin_panel_button(message: Message):
    if message.from_user.id == int(ADMIN_ID):
        await message.answer('Выберите параметр, который вас интересует', reply_markup=kb.stat_kb)
    else:
        await message.answer('У вас нет доступа')

@admin_router.message(F.text == 'Назад Админ')
async def help_main_button(message: Message):
    if message.from_user.id == int(ADMIN_ID):
        await message.answer('Вы вернулись в главное меню', reply_markup=kb.admin_panel)
    else:
        await message.answer('У вас нет доступа')

#TODO: Рассылка
@admin_router.message(F.text == 'Без фото')
async def help_main_button(message: Message):
    if message.from_user.id == int(ADMIN_ID):


        await message.answer('Отправка началась', reply_markup=kb.admin_panel)
    else:
        await message.answer('У вас нет доступа')