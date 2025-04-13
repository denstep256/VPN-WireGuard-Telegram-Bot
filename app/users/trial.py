import asyncio

from aiogram.types import CallbackQuery, FSInputFile
from aiogram import Router, F
from datetime import datetime, timedelta

from app.database.models import async_session, Static
from app.database.models import TestPeriod, User
from sqlalchemy import select, exists, delete

from app.users.handlers import texts_for_bot
from app.wg_api.wg_api import add_client_wg, get_config_wg

from app.addons.utilits import generate_client_name, check_available_clients_count

trial_router = Router()

@trial_router.callback_query(F.data.startswith('test_3_days'))
async def trial_button(call: CallbackQuery):
    # Выполняем проверку пробного периода и доступности файлов
    response_message, is_trial_not_activated = await check_trial_period(call.from_user.id)

    if is_trial_not_activated:
        available_conf = await check_available_clients_count()

    # Отправляем сообщение в зависимости от результата проверки
    await call.message.answer(response_message, parse_mode='HTML')

    if is_trial_not_activated and available_conf:
        await check_and_delete_user_in_static(call.from_user.id)
        async with async_session() as session:

            client_name = generate_client_name()
            expiry_date = (datetime.now() + timedelta(days=3)).date()
            # Если пользователя нет, активируем пробный период и сохраняем данные
            new_trial_user = TestPeriod(tg_id=call.from_user.id,
                                        username=call.from_user.username,
                                        file_name=client_name,
                                        subscription='trial',
                                        expiry_date=expiry_date,
                                        notif_oneday=False)
            session.add(new_trial_user)

            user = await session.execute(
                select(User).filter_by(tg_id=call.from_user.id)
            )
            user = user.scalar_one_or_none()

            if user:
                # Обновляем значения полей use_trial и is_active_trial
                user.use_trial = True
                user.is_active_trial = True
                session.add(user)
            await session.commit()

        await add_client_wg(client_name)
        await get_config_wg(client_name)
        await asyncio.sleep(1)
        file_path = f"app/auth/{client_name}.conf"   # Укажи правильный путь к файлу
        document = FSInputFile(file_path)
        await call.message.answer_document(document)


async def check_trial_period(tg_id):
    async with async_session() as session:
        # Проверка, что у пользователя test_period == 1
        user_exists = await session.scalar(
            select(exists().where(User.tg_id == tg_id, User.use_trial == 1))
        )

        # Проверка, что пользователь находится в таблице TestPeriod
        test_period_exists = await session.scalar(
            select(exists().where(TestPeriod.tg_id == tg_id))
        )

        if user_exists or test_period_exists:
            return texts_for_bot.get("TRIAL_ALREADY_USED"), False
        else:
            # Сообщение об успешной активации пробного периода
            return texts_for_bot.get("TRIAL_ACTIVATED"), True


async def check_and_delete_user_in_static(tg_id: int):
    async with async_session() as session:
        # Запрос к таблице Static для проверки пользователя по tg_id и use_trial == False
        query = select(Static).where(Static.tg_id == tg_id, Static.use_trial == False)
        result = await session.execute(query)
        user_in_static = result.scalar_one_or_none()

        # Если пользователь найден и use_trial == False
        if user_in_static:
            # Удаление записи из таблицы Static
            delete_query = delete(Static).where(Static.tg_id == tg_id)
            await session.execute(delete_query)
            await session.commit()  # Применение изменений
