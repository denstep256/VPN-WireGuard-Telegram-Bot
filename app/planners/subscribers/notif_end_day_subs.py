from datetime import datetime

from aiogram import Bot
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select, update, delete

from app.database.models import async_session, User, Subscribers
from app.addons.utilits import delete_file_by_name
from app.users.handlers import texts_for_bot
from app.wg_api.wg_api import remove_client_wg


# Функция для проверки подписок, которые истекают завтра
async def check_subscriptions_subs(bot: Bot):
    async with async_session() as session:
        now = (datetime.now()).date()

        # Запрос для поиска подписок, у которых истекает пробный период сегодня
        query = select(Subscribers).filter(Subscribers.expiry_date == now)
        result = await session.execute(query)
        expiring_subscriptions = result.scalars().all()


        # Отправляем уведомления пользователям, чьи подписки истекают
        for subscription in expiring_subscriptions:
            user_id = subscription.tg_id
            message = texts_for_bot["end_sub"]

            # Отправляем сообщение в Telegram
            await bot.send_message(chat_id=user_id, text=message, parse_mode='HTML')


            # Получение имени клиента для удаления
            query = select(Subscribers.file_name).filter(Subscribers.tg_id == user_id)
            result = await session.execute(query)
            client_name = result.scalars().first()

            delete_file_by_name(client_name)

            await remove_client_wg(client_name)


            # Обновление данных пользователя
            update_query = (
                update(User)
                .where(User.tg_id == user_id)
                .values(is_active_subs = False)
            )

            await session.execute(update_query)

            # Удаление записи из таблицы Subscribers
            delete_query = (
                delete(Subscribers)
                .where(Subscribers.tg_id == user_id)
            )
            await session.execute(delete_query)

        # Фиксация изменений в базе данных
        await session.commit()

# Настройка планировщика
def setup_scheduler_subs_notif_end_day(bot: Bot):

    # Инициализация планировщика
    scheduler = AsyncIOScheduler(timezone='Europe/Moscow')

    # Настройка задачи для проверки подписок (например, раз в день)
    scheduler.add_job(
        check_subscriptions_subs,
        trigger=IntervalTrigger(seconds=10),  # Задаём интервал выполнения
        id='check_subscriptions_subs_endday',
        kwargs={'bot': bot},
        replace_existing=True
    )

    # Запуск планировщика
    scheduler.start()
