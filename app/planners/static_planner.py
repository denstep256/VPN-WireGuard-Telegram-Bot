from datetime import date, timedelta

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select, update

from app.addons.utilits import parse_date_value
from app.database.models import Subscribers, TestPeriod, async_session


_scheduler: AsyncIOScheduler | None = None


async def update_static(bot: Bot):
    _ = bot
    tomorrow = date.today() + timedelta(days=1)

    async with async_session() as session:
        subs_result = await session.execute(
            select(Subscribers).where(Subscribers.notif_oneday == True)  # noqa: E712
        )
        subs = subs_result.scalars().all()
        for sub in subs:
            expiry = parse_date_value(sub.expiry_date)
            if expiry and expiry > tomorrow:
                await session.execute(
                    update(Subscribers).where(Subscribers.id == sub.id).values(notif_oneday=False)
                )

        trial_result = await session.execute(
            select(TestPeriod).where(
                TestPeriod.subscription == "trial",
                TestPeriod.notif_oneday == True,  # noqa: E712
            )
        )
        trials = trial_result.scalars().all()
        for trial in trials:
            expiry = parse_date_value(trial.expiry_date)
            if expiry and expiry > tomorrow:
                await session.execute(
                    update(TestPeriod).where(TestPeriod.id == trial.id).values(notif_oneday=False)
                )

        await session.commit()


def setup_scheduler_update_static(bot: Bot):
    global _scheduler
    if _scheduler and _scheduler.running:
        return

    _scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
    _scheduler.add_job(
        update_static,
        trigger=IntervalTrigger(hours=4),
        id="update_static",
        kwargs={"bot": bot},
        replace_existing=True,
    )
    _scheduler.start()
