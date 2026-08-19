from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
import logging

from app.addons.utilits import delete_file_by_name, parse_date_value, server_api_url
from app.database.models import Server, Subscribers, async_session
from app.planners.scheduler_runtime import get_scheduler
from app.time_utils import moscow_today
from app.wg_api.wg_api import remove_client_wg


logger = logging.getLogger(__name__)


async def check_subscriptions_subs(bot: Bot):
    today = moscow_today()
    processed = 0
    notified = 0
    failed_notify = 0
    failed_remove_remote = 0

    async with async_session() as session:
        result = await session.execute(select(Subscribers))
        subscriptions = result.scalars().all()

        for subscription in subscriptions:
            expiry = parse_date_value(subscription.expiry_date)
            if expiry is None or expiry > today:
                continue
            notified_marker = f"expired_notified:{expiry.isoformat()}"
            cleaned_marker = f"expired_cleaned:{expiry.isoformat()}"
            if subscription.note == cleaned_marker:
                continue
            processed += 1

            message = (
                "⚠️ <b>Срок подписки истёк</b>\n\n"
                f"Сервер: <b>{subscription.server_region} №{subscription.server_region_id}</b>\n"
                f"Дата окончания: <b>{expiry.isoformat()}</b>\n"
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

            if subscription.note != notified_marker:
                try:
                    await bot.send_message(
                        chat_id=subscription.tg_id,
                        text=message,
                        parse_mode="HTML",
                        reply_markup=renew_kb,
                    )
                    subscription.note = notified_marker
                    notified += 1
                except Exception:
                    failed_notify += 1
                    logger.exception(
                        "Failed to send end-day subscription notification: sub_id=%s tg_id=%s",
                        subscription.id,
                        subscription.tg_id,
                    )

            local_cleaned = True
            try:
                delete_file_by_name(subscription.file_name)
            except Exception:
                local_cleaned = False
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

            remote_cleaned = False
            if server:
                try:
                    await remove_client_wg(
                        subscription.file_name,
                        server_api_url(server),
                        server.password,
                    )
                    remote_cleaned = True
                except Exception:
                    failed_remove_remote += 1
                    logger.exception(
                        "Failed to remove WireGuard client for expired subscription: sub_id=%s file_name=%s region=%s region_id=%s",
                        subscription.id,
                        subscription.file_name,
                        subscription.server_region,
                        subscription.server_region_id,
                    )
            else:
                failed_remove_remote += 1
                logger.error(
                    "Server not found for expired subscription cleanup: sub_id=%s region=%s region_id=%s",
                    subscription.id,
                    subscription.server_region,
                    subscription.server_region_id,
                )

            if (
                remote_cleaned
                and local_cleaned
                and subscription.note == notified_marker
            ):
                subscription.note = cleaned_marker

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
        trigger=CronTrigger(hour=23, minute=45),
        id="check_subscriptions_subs_endday",
        kwargs={"bot": bot},
        replace_existing=True,
    )
    logger.info("Scheduler job registered: check_subscriptions_subs_endday (23:45 Europe/Moscow)")
