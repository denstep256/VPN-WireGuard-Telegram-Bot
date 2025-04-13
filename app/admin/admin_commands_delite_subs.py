from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from sqlalchemy import select, update, delete
from datetime import datetime, timedelta

from app.addons.utilits import determine_subscription_type
from app.database.models import async_session, Subscribers, User
from config import ADMIN_ID

admin_command_delite_subs_router = Router()

class ManualSubscriptionStateDelite(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_days = State()

# Шаг 1: Администратор инициирует удаление подписки
@admin_command_delite_subs_router.message(F.text == 'Убрать подписку')
async def issue_subscription(message: Message, state: FSMContext):
    if message.from_user.id == int(ADMIN_ID):
        await message.answer('Введите ID пользователя, которому нужно убрать подписку:')
        await state.set_state(ManualSubscriptionStateDelite.waiting_for_user_id)
    else:
        await message.answer('У вас нет доступа')

# Шаг 2: Получение ID пользователя и проверка наличия подписки
@admin_command_delite_subs_router.message(ManualSubscriptionStateDelite.waiting_for_user_id)
async def get_user_id(message: Message, state: FSMContext):
    tg_id = message.text
    async with async_session() as session:
        result = await session.execute(select(Subscribers).where(Subscribers.tg_id == tg_id))
        subscriber = result.scalar_one_or_none()

    if subscriber:
        await state.update_data(tg_id=tg_id)
        await message.answer('У пользователя найдена активная подписка. Введите количество дней, которые нужно убрать:')
        await state.set_state(ManualSubscriptionStateDelite.waiting_for_days)
    else:
        await message.answer('Пользователь не найден.')

# Шаг 3: Обновление подписки после вычитания дней или удаление записи
@admin_command_delite_subs_router.message(ManualSubscriptionStateDelite.waiting_for_days)
async def update_subscription(message: Message, state: FSMContext):
    try:
        days = int(message.text)
    except ValueError:
        await message.answer('Пожалуйста, введите корректное количество дней.')
        return

    data = await state.get_data()
    tg_id = data.get('tg_id')

    async with async_session() as session:
        # Получаем информацию о пользователе и подписке
        result = await session.execute(select(Subscribers).where(Subscribers.tg_id == tg_id))
        subscriber = result.scalar_one_or_none()

        if subscriber:
            # Преобразование даты окончания подписки
            current_expiry_date = datetime.strptime(subscriber.expiry_date, "%Y-%m-%d")
            new_expiry_date = current_expiry_date - timedelta(days=days)

            # Если новая дата окончания уже прошла, удаляем запись из Subscribers
            if new_expiry_date < datetime.now():
                await session.execute(
                    delete(Subscribers).where(Subscribers.tg_id == tg_id)
                )
                # Обновляем запись в таблице User, деактивируем подписку
                await session.execute(
                    update(User).where(User.tg_id == tg_id).values(
                        is_active_subs=False,
                        use_subs=True
                    )
                )
                await message.answer('Подписка полностью удалена, и запись о подписке была удалена.')
            else:
                # Обновляем дату окончания подписки
                await session.execute(
                    update(Subscribers).where(Subscribers.tg_id == tg_id).values(
                        expiry_date=new_expiry_date.strftime('%Y-%m-%d'),
                        note='manual_delite'
                    )
                )
                # Обновляем статус в таблице User
                await session.execute(
                    update(User).where(User.tg_id == tg_id).values(
                        is_active_subs=True,
                        use_subs=True
                    )
                )
                await message.answer(f'Подписка обновлена. Новая дата окончания: {new_expiry_date.strftime("%Y-%m-%d")}.')

            await session.commit()
        else:
            await message.answer('Подписка не найдена.')

    await state.clear()
