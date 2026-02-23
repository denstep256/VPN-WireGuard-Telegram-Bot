from datetime import date, timedelta

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select, update

from app.addons.utilits import parse_date_value
from app.database.models import TestPeriod, async_session


_scheduler: AsyncIOScheduler | None = None


async def check_subscriptions_trial(bot: Bot):
    tomorrow = date.today() + timedelta(days=1)

    async with async_session() as session:
        result = await session.execute(
            select(TestPeriod).where(
                TestPeriod.subscription == "trial",
                TestPeriod.notif_oneday == False,  # noqa: E712
            )
        )
        trials = result.scalars().all()

        for trial in trials:
            expiry = parse_date_value(trial.expiry_date)
            if expiry != tomorrow:
                continue

            message = (
                "⏳ <b>Пробный период заканчивается завтра</b>\n\n"
                f"Доступ действует до <b>{expiry.isoformat()}</b>.\n"
                "Чтобы не терять подключение, выберите платный тариф заранее."
            )

            try:
                await bot.send_message(chat_id=trial.tg_id, text=message, parse_mode="HTML")
                await session.execute(
                    update(TestPeriod)
                    .where(TestPeriod.id == trial.id)
                    .values(notif_oneday=True)
                )
            except Exception:
                continue

        await session.commit()


def setup_scheduler_trial_notif_oneday(bot: Bot):
    global _scheduler
    if _scheduler and _scheduler.running:
        return

    _scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
    _scheduler.add_job(
        check_subscriptions_trial,
        trigger=CronTrigger(hour=10, minute=15),
        id="check_subscriptions_trial_oneday",
        kwargs={"bot": bot},
        replace_existing=True,
    )
    _scheduler.start()
