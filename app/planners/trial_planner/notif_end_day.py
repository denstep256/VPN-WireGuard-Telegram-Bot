from aiogram import Bot
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
import logging

from app.addons.utilits import delete_file_by_name, parse_date_value, server_api_url
from app.database.models import Server, TestPeriod, async_session
from app.planners.scheduler_runtime import get_scheduler
from app.users.handlers import texts_for_bot
from app.time_utils import moscow_today
from app.wg_api.wg_api import remove_client_wg


logger = logging.getLogger(__name__)


async def check_subscriptions_trial(bot: Bot):
    today = moscow_today()
    processed = 0
    notified = 0
    failed_notify = 0
    failed_remove_remote = 0

    async with async_session() as session:
        trials_result = await session.execute(
            select(TestPeriod).where(
                TestPeriod.subscription.in_(("trial", "trial_expiring", "trial_pending"))
            )
        )
        trials = trials_result.scalars().all()

        for trial in trials:
            expiry = parse_date_value(trial.expiry_date)
            if expiry is None or expiry > today:
                continue
            processed += 1
            was_pending = trial.subscription == "trial_pending"

            if trial.subscription == "trial":
                try:
                    await bot.send_message(
                        chat_id=trial.tg_id,
                        text=texts_for_bot["end_trial_sub"],
                        parse_mode="HTML",
                    )
                    trial.subscription = "trial_expiring"
                    notified += 1
                except Exception:
                    failed_notify += 1
                    logger.exception(
                        "Failed to send end-day trial notification: trial_id=%s tg_id=%s",
                        trial.id,
                        trial.tg_id,
                    )

            cleanup_failed = False
            try:
                delete_file_by_name(trial.file_name)
            except Exception:
                cleanup_failed = True
                logger.exception(
                    "Failed to delete local trial config: trial_id=%s file_name=%s",
                    trial.id,
                    trial.file_name,
                )

            if trial.server_region and trial.server_region_id is not None:
                server_result = await session.execute(
                    select(Server).where(
                        Server.region == trial.server_region,
                        Server.region_id == trial.server_region_id,
                    )
                )
                server = server_result.scalar_one_or_none()
                servers = [server] if server else []
            else:
                # Legacy trial rows did not store the server; clean all servers once.
                servers_result = await session.execute(select(Server))
                servers = list(servers_result.scalars().all())

            cleanup_failed = cleanup_failed or not servers
            for server in servers:
                try:
                    await remove_client_wg(
                        trial.file_name,
                        server_api_url(server),
                        server.password,
                    )
                except Exception:
                    cleanup_failed = True
                    failed_remove_remote += 1
                    logger.exception(
                        "Failed to remove trial WireGuard client: trial_id=%s file_name=%s region=%s region_id=%s",
                        trial.id,
                        trial.file_name,
                        server.region,
                        server.region_id,
                    )
                    continue

            if cleanup_failed or (
                not was_pending and trial.subscription != "trial_expiring"
            ):
                logger.error(
                    "Trial cleanup remains pending: trial_id=%s tg_id=%s region=%s region_id=%s",
                    trial.id,
                    trial.tg_id,
                    trial.server_region,
                    trial.server_region_id,
                )
            elif was_pending:
                await session.delete(trial)
            else:
                trial.subscription = "trial_used"
                trial.notif_oneday = True

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
        trigger=CronTrigger(hour=23, minute=50),
        id="check_subscriptions_trial_endday",
        kwargs={"bot": bot},
        replace_existing=True,
    )
    logger.info("Scheduler job registered: check_subscriptions_trial_endday (23:50 Europe/Moscow)")
