from datetime import datetime
from aiogram import Bot
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select, update, delete

from app.database.models import async_session, TestPeriod, User
from app.addons.utilits import delete_file_by_name
from app.users.handlers import texts_for_bot
from app.wg_api.wg_api import remove_client_wg


# Функция для проверки подписок, которые истекают завтра
async def check_subscriptions_trial(bot: Bot):
    async with async_session() as session:
        now = (datetime.now()).date()

        # Запрос для поиска подписок, у которых истекает пробный период сегодня
        query = select(TestPeriod).filter(TestPeriod.expiry_date == now)
        result = await session.execute(query)
        expiring_subscriptions = result.scalars().all()


        # Отправляем уведомления пользователям, чьи подписки истекают
        for subscription in expiring_subscriptions:
            user_id = subscription.tg_id
            message = texts_for_bot["end_trial_sub"]

            # Отправляем сообщение в Telegram
            await bot.send_message(chat_id=user_id, text=message, parse_mode='HTML')


            # Получение имени клиента для удаления
            query = select(TestPeriod.file_name).filter(TestPeriod.tg_id == user_id)
            result = await session.execute(query)
            client_name = result.scalars().first()

            delete_file_by_name(client_name)

            await remove_client_wg(client_name)


            # Обновление данных пользователя
            update_query = (
                update(User)
                .where(User.tg_id == user_id)
                .values(is_active_trial=False)
            )
            await session.execute(update_query)

            # Удаление записи из таблицы TestPeriod
            delete_query = (
                delete(TestPeriod)
                .where(TestPeriod.tg_id == user_id)
            )
            await session.execute(delete_query)

        # Фиксация изменений в базе данных
        await session.commit()

# Настройка планировщика
def setup_scheduler_trial_notif_end_day(bot: Bot):

    # Инициализация планировщика
    scheduler = AsyncIOScheduler(timezone='Europe/Moscow')

    # Настройка задачи для проверки подписок (например, раз в день)
    scheduler.add_job(
        check_subscriptions_trial,
        trigger=IntervalTrigger(hours=8),  # Задаём интервал выполнения
        id='check_subscriptions_trial_end_day',
        kwargs={'bot': bot},
        replace_existing=True
    )

    # Запуск планировщика
    scheduler.start()