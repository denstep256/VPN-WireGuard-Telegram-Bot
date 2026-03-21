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

    async with async_session() as session:
        result = await session.execute(select(Subscribers))
        subscriptions = result.scalars().all()

        for subscription in subscriptions:
            expiry = parse_date_value(subscription.expiry_date)
            if expiry != today:
                continue
            if subscription.note == marker:
                continue

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
            except Exception:
                logger.exception(
                    "Failed to send end-day subscription notification: sub_id=%s tg_id=%s",
                    subscription.id,
                    subscription.tg_id,
                )

            delete_file_by_name(subscription.file_name)

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
                    pass

            await session.execute(
                update(Subscribers)
                .where(Subscribers.id == subscription.id)
                .values(note=marker)
            )

        await session.commit()


def setup_scheduler_subs_notif_end_day(bot: Bot):
    scheduler = get_scheduler()
    scheduler.add_job(
        check_subscriptions_subs,
        trigger=CronTrigger(hour=11, minute=0),
        id="check_subscriptions_subs_endday",
        kwargs={"bot": bot},
        replace_existing=True,
    )
    logger.info("Scheduler job registered: check_subscriptions_subs_endday (11:00 Europe/Moscow)")
