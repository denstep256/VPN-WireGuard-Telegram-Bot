import logging
from datetime import date, timedelta

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select, update

from app.addons.utilits import parse_date_value
from app.database.models import Subscribers, async_session
from app.planners.scheduler_runtime import get_scheduler
from app.vpn.provisioning import format_service_location, get_protocol_label, get_record_protocol


logger = logging.getLogger(__name__)


async def check_subscriptions(bot: Bot):
    tomorrow = date.today() + timedelta(days=1)
    processed = 0
    sent = 0
    failed = 0

    async with async_session() as session:
        result = await session.execute(
            select(Subscribers).where(Subscribers.notif_oneday == False)  # noqa: E712
        )
        subscriptions = result.scalars().all()

        for subscription in subscriptions:
            expiry = parse_date_value(subscription.expiry_date)
            if expiry != tomorrow:
                continue
            processed += 1

            message = (
                "⏳ <b>Напоминание о подписке</b>\n\n"
                f"Протокол: <b>{get_protocol_label(get_record_protocol(subscription))}</b>\n"
                f"Срок доступа к серверу <b>{format_service_location(get_record_protocol(subscription), subscription.server_region, subscription.server_region_id)}</b> "
                f"заканчивается <b>{expiry.isoformat()}</b>.\n"
                "Продлите сейчас, чтобы не терять подключение."
            )

            renew_kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🔁 Продлить подписку",
                            callback_data=f"renew_open|{subscription.id}",
                        )
                    ]
                ]
            )

            try:
                await bot.send_message(
                    chat_id=subscription.tg_id,
                    text=message,
                    parse_mode="HTML",
                    reply_markup=renew_kb,
                )
                await session.execute(
                    update(Subscribers)
                    .where(Subscribers.id == subscription.id)
                    .values(notif_oneday=True)
                )
                sent += 1
            except Exception:
                failed += 1
                logger.exception(
                    "Failed to send 1-day subscription notification: sub_id=%s tg_id=%s",
                    subscription.id,
                    subscription.tg_id,
                )
                continue

        await session.commit()
    logger.info(
        "Scheduler run check_subscriptions_oneday finished: processed=%s sent=%s failed=%s target_date=%s",
        processed,
        sent,
        failed,
        tomorrow.isoformat(),
    )


def setup_scheduler_subs_notif_oneday(bot: Bot):
    scheduler = get_scheduler()
    scheduler.add_job(
        check_subscriptions,
        trigger=CronTrigger(hour=18, minute=57),
        id="check_subscriptions_oneday",
        kwargs={"bot": bot},
        replace_existing=True,
    )
    logger.info("Scheduler job registered: check_subscriptions_oneday (10:00 Europe/Moscow)")
