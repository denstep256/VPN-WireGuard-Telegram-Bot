from datetime import date

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select, update

from app.addons.utilits import delete_file_by_name, parse_date_value
from app.database.models import Server, TestPeriod, async_session
from app.users.handlers import texts_for_bot
from app.wg_api.wg_api import remove_client_wg


_scheduler: AsyncIOScheduler | None = None


async def check_subscriptions_trial(bot: Bot):
    today = date.today()

    async with async_session() as session:
        trials_result = await session.execute(select(TestPeriod).where(TestPeriod.subscription == "trial"))
        trials = trials_result.scalars().all()

        servers_result = await session.execute(select(Server))
        servers = servers_result.scalars().all()

        for trial in trials:
            expiry = parse_date_value(trial.expiry_date)
            if expiry != today:
                continue

            try:
                await bot.send_message(
                    chat_id=trial.tg_id,
                    text=texts_for_bot["end_trial_sub"],
                    parse_mode="HTML",
                )
            except Exception:
                pass

            delete_file_by_name(trial.file_name)

            for server in servers:
                try:
                    await remove_client_wg(
                        trial.file_name,
                        f"https://{server.host_ip}:{server.port}",
                        server.password,
                    )
                except Exception:
                    continue

            await session.execute(
                update(TestPeriod)
                .where(TestPeriod.id == trial.id)
                .values(subscription="trial_used", notif_oneday=True)
            )

        await session.commit()


def setup_scheduler_trial_notif_end_day(bot: Bot):
    global _scheduler
    if _scheduler and _scheduler.running:
        return

    _scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
    _scheduler.add_job(
        check_subscriptions_trial,
        trigger=CronTrigger(hour=11, minute=15),
        id="check_subscriptions_trial_endday",
        kwargs={"bot": bot},
        replace_existing=True,
    )
    _scheduler.start()
