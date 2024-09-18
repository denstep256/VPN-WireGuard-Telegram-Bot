import asyncio

from datetime import datetime
from aiogram import Bot
from sqlalchemy.orm import sessionmaker
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.payments.models import IssuedKey
from app.payments.requests import get_db



async def update_expired_subscriptions(bot: Bot, db_session: sessionmaker):

    db = next(db_session)
    today = datetime.now().date()
    subscriptions_to_update = db.query(IssuedKey).filter(
        IssuedKey.expiry_date <= today,
        IssuedKey.is_used == True
    ).all()

    for subscription in subscriptions_to_update:
        subscription.is_used = False

    db.commit()
    db.close()



scheduler = AsyncIOScheduler()


def setup_update_scheduler(bot: Bot):
    def job_function():

        asyncio.run(update_expired_subscriptions(bot, get_db()))

    scheduler.add_job(
        func=job_function,
        trigger='interval',
        hours=4,
        id='update_expired_subscriptions'
    )
    scheduler.start()
