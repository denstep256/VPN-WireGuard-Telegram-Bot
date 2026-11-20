import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy import select, text

import config
from app.addons.utilits import check_available_clients_count, generate_client_name
from app.database.models import TestPeriod, async_session, refresh_user_protocol
from app.users.handlers import texts_for_bot
from app.vpn.provisioning import PROTOCOL_BOTH, create_vpn_access, send_access_to_user

trial_router = Router()
logger = logging.getLogger(__name__)


@trial_router.callback_query(F.data.split("|")[0] == "test_3_days")
async def trial_button(call: CallbackQuery):
    tg_id = call.from_user.id
    username = call.from_user.username
    expiry = (datetime.now(ZoneInfo(config.VPN_TIMEZONE)).date() + timedelta(days=3)).isoformat()
    await call.answer()
    try:
        async with async_session.begin() as session:
            await session.execute(text("BEGIN IMMEDIATE"))
            record = await session.scalar(select(TestPeriod).where(TestPeriod.tg_id == tg_id).limit(1))
            if record is not None and record.subscription != "trial_pending":
                await call.message.answer(texts_for_bot["TRIAL_ALREADY_USED"], parse_mode="HTML")
                return
            if record is None:
                if not await check_available_clients_count():
                    await call.message.answer("⚠️ Пробный доступ временно недоступен.")
                    return
                record = TestPeriod(
                    tg_id=tg_id, username=username, file_name=await generate_client_name(session),
                    subscription="trial_pending", expiry_date=expiry, protocol=PROTOCOL_BOTH,
                    notif_oneday=False,
                )
                session.add(record)
            record.expiry_date = expiry
            await session.flush()
            record_id = record.id

        async with async_session.begin() as session:
            await session.execute(text("BEGIN IMMEDIATE"))
            record = await session.get(TestPeriod, record_id)
            if record is None or record.subscription != "trial_pending":
                return
            access = await create_vpn_access(
                protocol=PROTOCOL_BOTH, client_name=record.file_name, expiry_date=record.expiry_date,
                tg_id=tg_id, username=username,
            )
            record.subscription = "trial"
            record.xui_sub_id = access.xui_sub_id
            await refresh_user_protocol(session, tg_id)
    except Exception:
        logger.exception("Не удалось выдать пробный доступ пользователю %s", tg_id)
        await call.message.answer(
            "⚠️ Не удалось выдать пробную конфигурацию. Попробуйте ещё раз или напишите в поддержку."
        )
        return

    await call.message.answer(texts_for_bot["TRIAL_ACTIVATED"], parse_mode="HTML")
    await send_access_to_user(call.message, access)
