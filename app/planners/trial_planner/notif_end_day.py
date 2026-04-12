from datetime import date

from aiogram import Bot
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select, update
import logging

from app.addons.utilits import delete_file_by_name, parse_date_value
from app.database.models import Server, TestPeriod, async_session
from app.planners.scheduler_runtime import get_scheduler
from app.users.handlers import texts_for_bot
from app.wg_api.wg_api import remove_client_wg


logger = logging.getLogger(__name__)


async def check_subscriptions_trial(bot: Bot):
    today = date.today()
    processed = 0
    notified = 0
    failed_notify = 0
    failed_remove_remote = 0

    async with async_session() as session:
        trials_result = await session.execute(select(TestPeriod).where(TestPeriod.subscription == "trial"))
        trials = trials_result.scalars().all()

        servers_result = await session.execute(select(Server))
        servers = servers_result.scalars().all()

        for trial in trials:
            expiry = parse_date_value(trial.expiry_date)
            if expiry != today:
                continue
            processed += 1

            try:
                await bot.send_message(
                    chat_id=trial.tg_id,
                    text=texts_for_bot["end_trial_sub"],
                    parse_mode="HTML",
                )
                notified += 1
            except Exception:
                failed_notify += 1
                logger.exception(
                    "Failed to send end-day trial notification: trial_id=%s tg_id=%s",
                    trial.id,
                    trial.tg_id,
                )

            delete_file_by_name(trial.file_name)

            for server in servers:
                try:
                    await remove_client_wg(
                        trial.file_name,
                        f"https://{server.host_ip}:{server.port}",
                        server.password,
                    )
                except Exception:
                    failed_remove_remote += 1
                    logger.exception(
                        "Failed to remove trial WireGuard client: trial_id=%s file_name=%s region=%s region_id=%s",
                        trial.id,
                        trial.file_name,
                        server.region,
                        server.region_id,
                    )
                    continue

            await session.execute(
                update(TestPeriod)
                .where(TestPeriod.id == trial.id)
                .values(subscription="trial_used", notif_oneday=True)
            )

        await session.commit()
    logger.info(
        "Scheduler run check_subscriptions_trial_endday finished: processed=%s notified=%s failed_notify=%s failed_remove_remote=%s target_date=%s",
        processed,
        notified,
        failed_notify,
        failed_remove_remote,
        today.isoformat(),
    )


def setup_scheduler_trial_notif_end_day(bot: Bot):
    scheduler = get_scheduler()
    scheduler.add_job(
        check_subscriptions_trial,
        #trigger=CronTrigger(hour=11, minute=15),
        trigger=CronTrigger(hour=18, minute=57),
        id="check_subscriptions_trial_endday",
        kwargs={"bot": bot},
        replace_existing=True,
    )
    logger.info("Scheduler job registered: check_subscriptions_trial_endday (11:15 Europe/Moscow)")
