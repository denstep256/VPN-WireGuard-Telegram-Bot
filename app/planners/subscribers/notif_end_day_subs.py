import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import func, select, text

import config
from app.addons.utilits import parse_date_value
from app.database.models import Subscribers, async_session, refresh_user_protocol
from app.planners.scheduler_runtime import get_scheduler
from app.vpn.provisioning import get_protocol_label, get_record_protocol, remove_vpn_access

logger = logging.getLogger(__name__)


async def check_subscriptions_subs(bot: Bot):
    today = datetime.now(ZoneInfo(config.VPN_TIMEZONE)).date()
    async with async_session.begin() as session:
        await refresh_user_protocol(session)
        ids = (await session.scalars(select(Subscribers.id).where(
            func.date(Subscribers.expiry_date) < today.isoformat(),
        ))).all()

    for sub_id in ids:
        try:
            async with async_session.begin() as session:
                await session.execute(text("BEGIN IMMEDIATE"))
                subscription = await session.get(Subscribers, sub_id)
                if subscription is None:
                    continue
                expiry = parse_date_value(subscription.expiry_date)
                marker = f"expired_notified:{expiry}"
                if expiry is None or expiry >= today or subscription.note == marker:
                    continue
                protocol = get_record_protocol(subscription)
                await remove_vpn_access(protocol=protocol, client_name=subscription.file_name)
                subscription.note = marker
                if not subscription.provisioned or (today - expiry).days > 1:
                    continue
        except Exception:
            logger.exception("Не удалось отозвать просроченный доступ: sub_id=%s", sub_id)
            continue

        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🔁 Продлить подписку", callback_data=f"renew_open|{sub_id}")
        ]])
        try:
            await bot.send_message(
                subscription.tg_id,
                f"⚠️ <b>Срок подписки {get_protocol_label(protocol)} истёк</b>\n\n"
                "Продлите подписку, чтобы вернуть доступ.",
                parse_mode="HTML", reply_markup=keyboard,
            )
        except Exception:
            logger.exception("Не удалось отправить уведомление об окончании подписки: sub_id=%s", sub_id)


def setup_scheduler_subs_notif_end_day(bot: Bot):
    get_scheduler().add_job(
        check_subscriptions_subs,
        trigger=CronTrigger(hour=0, minute=5, timezone=config.VPN_TIMEZONE),
        id="check_subscriptions_subs_endday",
        kwargs={"bot": bot},
        replace_existing=True,
    )
