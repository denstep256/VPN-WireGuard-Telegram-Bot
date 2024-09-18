import asyncio
from datetime import datetime, timedelta
from aiogram import Bot
from sqlalchemy.orm import sessionmaker
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.payments.models import IssuedKey
from app.payments.requests import get_db

# Функция для отправки уведомления пользователю
async def send_notification(bot: Bot, user_id: int):
    message = "Ваша подписка заканчивается завтра!"
    await bot.send_message(chat_id=user_id, text=message)

# Функция для проверки подписок, которые истекают завтра
async def check_subscriptions(bot: Bot, db_session: sessionmaker):
    db = next(db_session)
    tomorrow = datetime.now().date() + timedelta(days=1)
    subscriptions = db.query(IssuedKey).filter(
        IssuedKey.expiry_date == tomorrow,
        IssuedKey.is_used == True
    ).all()

    for subscription in subscriptions:
        await send_notification(bot, subscription.user_id)

    db.commit()
    db.close()

# Планировщик уведомлений
scheduler = AsyncIOScheduler()

# Настройка планировщика
def setup_send_notifications(bot: Bot):
    async def job_function():
        await check_subscriptions(bot, get_db())

    # Получаем текущий event loop
    loop = asyncio.get_event_loop()
    scheduler.add_job(
        func=lambda: asyncio.run_coroutine_threadsafe(job_function(), loop).result(),
        trigger='interval',
        days=1,
        id='check_subscriptions'
    )
    scheduler.start()
