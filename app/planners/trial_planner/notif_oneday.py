from datetime import date, timedelta

from aiogram import Bot
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select, update
import logging

from app.addons.utilits import parse_date_value
from app.database.models import TestPeriod, async_session
from app.planners.scheduler_runtime import get_scheduler
from app.vpn.provisioning import get_protocol_label, get_record_protocol


logger = logging.getLogger(__name__)


async def check_subscriptions_trial(bot: Bot):
    tomorrow = date.today() + timedelta(days=1)
    processed = 0
    sent = 0
    failed = 0

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
            processed += 1

            message = (
                "⏳ <b>Пробный период заканчивается завтра</b>\n\n"
                f"Протокол: <b>{get_protocol_label(get_record_protocol(trial))}</b>\n"
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
                sent += 1
            except Exception:
                failed += 1
                logger.exception(
                    "Failed to send 1-day trial notification: trial_id=%s tg_id=%s",
                    trial.id,
                    trial.tg_id,
                )
                continue

        await session.commit()
    logger.info(
        "Scheduler run check_subscriptions_trial_oneday finished: processed=%s sent=%s failed=%s target_date=%s",
        processed,
        sent,
        failed,
        tomorrow.isoformat(),
    )


def setup_scheduler_trial_notif_oneday(bot: Bot):
    scheduler = get_scheduler()
    scheduler.add_job(
        check_subscriptions_trial,
        trigger=CronTrigger(hour=18, minute=57),
        id="check_subscriptions_trial_oneday",
        kwargs={"bot": bot},
        replace_existing=True,
    )
    logger.info("Scheduler job registered: check_subscriptions_trial_oneday (10:15 Europe/Moscow)")
