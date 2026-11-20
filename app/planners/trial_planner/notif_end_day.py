import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Bot
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import func, select, text

import config
from app.addons.utilits import parse_date_value
from app.database.models import TestPeriod, async_session, refresh_user_protocol
from app.planners.scheduler_runtime import get_scheduler
from app.users.handlers import texts_for_bot
from app.vpn.provisioning import get_record_protocol, remove_vpn_access

logger = logging.getLogger(__name__)


async def check_subscriptions_trial(bot: Bot):
    today = datetime.now(ZoneInfo(config.VPN_TIMEZONE)).date()
    async with async_session() as session:
        ids = (await session.scalars(select(TestPeriod.id).where(
            TestPeriod.subscription.in_(("trial", "trial_pending")), func.date(TestPeriod.expiry_date) < today.isoformat(),
        ))).all()

    for trial_id in ids:
        try:
            async with async_session.begin() as session:
                await session.execute(text("BEGIN IMMEDIATE"))
                trial = await session.get(TestPeriod, trial_id)
                if trial is None or trial.subscription not in {"trial", "trial_pending"}:
                    continue
                expiry = parse_date_value(trial.expiry_date)
                if expiry is None or expiry >= today:
                    continue
                await remove_vpn_access(protocol=get_record_protocol(trial), client_name=trial.file_name)
                if trial.subscription == "trial_pending":
                    await session.delete(trial)
                    continue
                trial.subscription = "trial_used"
                trial.notif_oneday = True
                await refresh_user_protocol(session, trial.tg_id)
        except Exception:
            logger.exception("Не удалось отозвать пробный доступ: trial_id=%s", trial_id)
            continue

        if (today - expiry).days > 1:
            continue
        try:
            await bot.send_message(trial.tg_id, texts_for_bot["end_trial_sub"], parse_mode="HTML")
        except Exception:
            logger.exception("Не удалось отправить уведомление о пробном доступе: trial_id=%s", trial_id)


def setup_scheduler_trial_notif_end_day(bot: Bot):
    get_scheduler().add_job(
        check_subscriptions_trial,
        trigger=CronTrigger(hour=0, minute=6, timezone=config.VPN_TIMEZONE),
        id="check_subscriptions_trial_notif_end_day",
        kwargs={"bot": bot},
        replace_existing=True,
    )
