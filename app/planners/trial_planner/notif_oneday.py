from datetime import datetime, timedelta
from aiogram import Bot
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select, update
from app.database.models import async_session, TestPeriod


# Функция для проверки подписок, которые истекают завтра
async def check_subscriptions_trial(bot: Bot):
    async with async_session() as session:
        tomorrow = datetime.now() + timedelta(days=1)

        # Запрос для поиска подписок, у которых истекает пробный период завтра
        query = select(TestPeriod).filter(TestPeriod.expiry_date == tomorrow.date())

        result = await session.execute(query)
        expiring_subscriptions = result.scalars().all()

        # Отправляем уведомления пользователям, чьи подписки истекают
        for subscription in expiring_subscriptions:
            user_id = subscription.tg_id
            message = f"Ваша пробная подписка заканчивается завтра {subscription.expiry_date}."

            # Отправляем сообщение в Telegram
            await bot.send_message(chat_id=user_id, text=message)
            update_query = (
                update(TestPeriod)
                .where(TestPeriod.tg_id == user_id)
                .values(notif_oneday=1)
            )
            await session.execute(update_query)


        await session.commit()


# Настройка планировщика
def setup_scheduler_trial_notif_oneday(bot: Bot):

    # Инициализация планировщика
    scheduler = AsyncIOScheduler()

    # Настройка задачи для проверки подписок (например, раз в день)
    scheduler.add_job(
        check_subscriptions_trial,
        trigger=IntervalTrigger(hours=8),  # Задаём интервал выполнения
        id='check_subscriptions',
        kwargs={'bot': bot},
        replace_existing=True
    )

    # Запуск планировщика
    scheduler.start()

