from datetime import datetime, timedelta
from aiogram import Bot
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select, update
from app.database.models import async_session, Subscribers


# Функция для проверки подписок, которые истекают завтра
async def check_subscriptions(bot: Bot):
    async with async_session() as session:
        tomorrow = datetime.now() + timedelta(days=1)

        # Запрос для поиска подписок, у которых истекает пробный период завтра
        query = select(Subscribers).filter(Subscribers.expiry_date == tomorrow.date())

        result = await session.execute(query)
        expiring_subscriptions = result.scalars().all()

        # Отправляем уведомления пользователям, чьи подписки истекают
        for subscription in expiring_subscriptions:
            user_id = subscription.tg_id
            message = f"⏳ Ваша подписка истекает завтра, {subscription.expiry_date}.\nНе забудьте продлить, чтобы не потерять доступ! 🚀"
            #TODO: Добавить чтобы после соообщения присылался счет на оплату подписки

            # Отправляем сообщение в Telegram
            await bot.send_message(chat_id=user_id, text=message, parse_mode='HTML')
            update_query = (
                update(Subscribers)
                .where(Subscribers.tg_id == user_id)
                .values(notif_oneday=1)
            )
            await session.execute(update_query)


        await session.commit()


# Настройка планировщика
def setup_scheduler_subs_notif_oneday(bot: Bot):

    # Инициализация планировщика
    scheduler = AsyncIOScheduler(timezone='Europe/Moscow')

    # Настройка задачи для проверки подписок (например, раз в день)
    scheduler.add_job(
        check_subscriptions,
        trigger=IntervalTrigger(seconds=10),  # Задаём интервал выполнения
        id='check_subscriptions_oneday',
        kwargs={'bot': bot},
        replace_existing=True
    )

    # Запуск планировщика
    scheduler.start()

