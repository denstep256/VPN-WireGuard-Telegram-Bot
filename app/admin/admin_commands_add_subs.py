import asyncio

from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from sqlalchemy import select, update
from datetime import datetime, timedelta

from app.addons.utilits import generate_client_name, determine_subscription_type
from app.database.models import async_session, Subscribers, User
from app.wg_api.wg_api import add_client_wg, get_config_wg
from config import ADMIN_ID

admin_command_add_subs_router = Router()

class ManualSubscriptionState(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_days = State()

@admin_command_add_subs_router.message(F.text == 'Выдать подписку')
async def issue_subscription(message: Message, state: FSMContext):
    if message.from_user.id == int(ADMIN_ID):
        await message.answer('Введите ID пользователя, которому нужно выдать подписку:')
        await state.set_state(ManualSubscriptionState.waiting_for_user_id)
    else:
        await message.answer('У вас нет доступа')


@admin_command_add_subs_router.message(ManualSubscriptionState.waiting_for_user_id)
async def get_user_id(message: Message, state: FSMContext):
    tg_id = message.text
    async with async_session() as session:
        # Сначала проверяем таблицу Subscribers
        result = await session.execute(select(Subscribers).where(Subscribers.tg_id == tg_id))
        subscriber = result.scalar_one_or_none()

        if not subscriber:
            # Если в Subscribers не найден, проверяем таблицу User
            result = await session.execute(select(User).where(User.tg_id == tg_id))
            user = result.scalar_one_or_none()

        await session.commit()

    await state.update_data(tg_id=tg_id)

    if subscriber:
        await message.answer(
            'У пользователя найдена активная подписка. Введите количество дней, которые нужно добавить:')
        await state.set_state(ManualSubscriptionState.waiting_for_days)
    elif user:
        await message.answer('Пользователь найден в системе. Введите количество дней, которые нужно добавить:')
        await state.set_state(ManualSubscriptionState.waiting_for_days)
    else:
        await message.answer('Пользователь не найден в системе.')
        await state.clear()  # Сбрасываем состояние, если пользователь не найден


@admin_command_add_subs_router.message(ManualSubscriptionState.waiting_for_days)
async def update_subscription(message: Message, state: FSMContext):
    try:
        days = int(message.text)
    except ValueError:
        await message.answer('Пожалуйста, введите корректное количество дней.')
        return

    data = await state.get_data()
    tg_id = data.get('tg_id')
    new_expiry_date = datetime.now() + timedelta(days=days)

    subscription_type = determine_subscription_type(days)

    async with async_session() as session:
        # Получаем username из User
        user_result = await session.execute(select(User).where(User.tg_id == tg_id))
        user = user_result.scalar_one_or_none()
        username = user.username if user else None

        # Проверяем, существует ли пользователь в Subscribers
        result = await session.execute(select(Subscribers).where(Subscribers.tg_id == tg_id))
        subscriber = result.scalar_one_or_none()


        if subscriber:
            current_date = subscriber.expiry_date
            current_date = datetime.strptime(current_date, "%Y-%m-%d")
            new_expiry_date_new = (current_date + timedelta(days=days)).date()
            await session.execute(
                update(Subscribers).where(Subscribers.tg_id == tg_id).values(
                    expiry_date=new_expiry_date_new.strftime('%Y-%m-%d'),
                    note='manual_update',
                    subscription=subscription_type
                )
            )
        else:
            # Создаем новую запись
            new_subscriber = Subscribers(
                tg_id=tg_id,
                username=username,  # Используем username из таблицы User
                file_name='check_manual',
                subscription=subscription_type,
                expiry_date=new_expiry_date.strftime('%Y-%m-%d'),
                notif_oneday=False,
                note='manual_add'
            )
            session.add(new_subscriber)

            if new_subscriber.file_name == 'check_manual':
                client_name = generate_client_name()
                await add_client_wg(client_name)
                await get_config_wg(client_name)
                await asyncio.sleep(1)
                update_query = (
                    update(Subscribers)
                    .where(Subscribers.tg_id == tg_id)
                    .values(file_name=client_name)
                )
                await session.execute(update_query)

        # Обновляем активные подписки в таблице User

        await session.execute(
            update(User).where(User.tg_id == tg_id).values(
                is_active_subs=True,
                use_subs=True
            )
        )


        await session.commit()

    await message.answer(f'Подписка выдана на {days} дней.')

    await state.clear()


