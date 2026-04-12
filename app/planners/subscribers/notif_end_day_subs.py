from datetime import date

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select, update
import logging

from app.addons.utilits import delete_file_by_name, parse_date_value
from app.database.models import Server, Subscribers, async_session
from app.planners.scheduler_runtime import get_scheduler
from app.wg_api.wg_api import remove_client_wg


logger = logging.getLogger(__name__)


async def check_subscriptions_subs(bot: Bot):
    today = date.today()
    marker = f"expired_notified:{today.isoformat()}"
    processed = 0
    notified = 0
    failed_notify = 0
    failed_remove_remote = 0

    async with async_session() as session:
        result = await session.execute(select(Subscribers))
        subscriptions = result.scalars().all()

        for subscription in subscriptions:
            expiry = parse_date_value(subscription.expiry_date)
            if expiry != today:
                continue
            if subscription.note == marker:
                continue
            processed += 1

            message = (
                "⚠️ <b>Срок подписки истёк сегодня</b>\n\n"
                f"Сервер: <b>{subscription.server_region} №{subscription.server_region_id}</b>\n"
                "Чтобы вернуть доступ, продлите подписку одним нажатием."
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
                notified += 1
            except Exception:
                failed_notify += 1
                logger.exception(
                    "Failed to send end-day subscription notification: sub_id=%s tg_id=%s",
                    subscription.id,
                    subscription.tg_id,
                )

            try:
                delete_file_by_name(subscription.file_name)
            except Exception:
                logger.exception(
                    "Failed to delete local file for expired subscription: sub_id=%s file_name=%s",
                    subscription.id,
                    subscription.file_name,
                )

            server_result = await session.execute(
                select(Server).where(
                    Server.region == subscription.server_region,
                    Server.region_id == subscription.server_region_id,
                )
            )
            server = server_result.scalar_one_or_none()

            if server:
                try:
                    await remove_client_wg(
                        subscription.file_name,
                        f"https://{server.host_ip}:{server.port}",
                        server.password,
                    )
                except Exception:
                    failed_remove_remote += 1
                    logger.exception(
                        "Failed to remove WireGuard client for expired subscription: sub_id=%s file_name=%s region=%s region_id=%s",
                        subscription.id,
                        subscription.file_name,
                        subscription.server_region,
                        subscription.server_region_id,
                    )

            await session.execute(
                update(Subscribers)
                .where(Subscribers.id == subscription.id)
                .values(note=marker)
            )

        await session.commit()
    logger.info(
        "Scheduler run check_subscriptions_subs_endday finished: processed=%s notified=%s failed_notify=%s failed_remove_remote=%s target_date=%s",
        processed,
        notified,
        failed_notify,
        failed_remove_remote,
        today.isoformat(),
    )


def setup_scheduler_subs_notif_end_day(bot: Bot):
    scheduler = get_scheduler()
    scheduler.add_job(
        check_subscriptions_subs,
        trigger=CronTrigger(hour=18, minute=57),
        #trigger=CronTrigger(hour=14, minute=10),
        id="check_subscriptions_subs_endday",
        kwargs={"bot": bot},
        replace_existing=True,
    )
    logger.info("Scheduler job registered: check_subscriptions_subs_endday (11:00 Europe/Moscow)")
