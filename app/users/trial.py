import logging
from datetime import timedelta

from aiogram import F, Router
from aiogram.types import CallbackQuery, FSInputFile
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.addons.utilits import (
    check_available_clients_count,
    generate_client_name,
    server_api_url,
)
from app.database.models import Server, TestPeriod, async_session
from app.users.handlers import texts_for_bot
from app.time_utils import moscow_today
from app.wg_api.wg_api import WireGuardCapacityError, provision_client_wg


trial_router = Router()
logger = logging.getLogger(__name__)


def _parse_trial_callback(data: str) -> tuple[str | None, int | None]:
    parts = (data or "").split("|")
    if len(parts) != 3 or parts[0] != "test_3_days":
        return None, None
    region = parts[1]
    if not region or not parts[2].isdigit():
        return None, None
    region_id = int(parts[2])
    if region_id <= 0:
        return None, None
    return region, region_id


async def _get_trial(tg_id: int) -> TestPeriod | None:
    async with async_session() as session:
        result = await session.execute(
            select(TestPeriod)
            .where(TestPeriod.tg_id == tg_id)
            .order_by(TestPeriod.id)
            .limit(1)
        )
        return result.scalar_one_or_none()


@trial_router.callback_query(F.data.startswith("test_3_days|"))
async def trial_button(call: CallbackQuery):
    requested_region, requested_region_id = _parse_trial_callback(call.data)
    if not requested_region or requested_region_id is None:
        await call.answer("❌ Некорректные данные сервера.", show_alert=True)
        return

    tg_id = call.from_user.id
    trial = await _get_trial(tg_id)
    if trial and trial.subscription != "trial_pending":
        await call.message.answer(texts_for_bot["TRIAL_ALREADY_USED"], parse_mode="HTML")
        await call.answer()
        return

    if trial:
        region = trial.server_region
        region_id = trial.server_region_id
        client_name = trial.file_name
        expiry_date = trial.expiry_date
        if not region or region_id is None:
            logger.error("Pending trial has no server: trial_id=%s tg_id=%s", trial.id, tg_id)
            await call.message.answer(
                "⚠️ Незавершённый пробный период требует ручной проверки. Напишите в поддержку."
            )
            await call.answer()
            return
    else:
        region = requested_region
        region_id = requested_region_id
        if not await check_available_clients_count(region=region, region_id=region_id):
            await call.message.answer(
                "⚠️ На выбранном сервере сейчас нет свободных мест для пробного периода. "
                "Попробуйте другой сервер.",
                parse_mode="HTML",
            )
            await call.answer()
            return

        client_name = generate_client_name()
        expiry_date = (moscow_today() + timedelta(days=3)).isoformat()
        try:
            async with async_session() as session:
                trial = TestPeriod(
                    tg_id=tg_id,
                    username=call.from_user.username or "unknown",
                    file_name=client_name,
                    subscription="trial_pending",
                    expiry_date=expiry_date,
                    notif_oneday=False,
                    server_region=region,
                    server_region_id=region_id,
                )
                session.add(trial)
                await session.commit()
                await session.refresh(trial)
        except IntegrityError:
            logger.info("Concurrent duplicate trial was rejected: tg_id=%s", tg_id)
            await call.message.answer(texts_for_bot["TRIAL_ALREADY_USED"], parse_mode="HTML")
            await call.answer()
            return

    async with async_session() as session:
        server_result = await session.execute(
            select(Server).where(
                Server.region == region,
                Server.region_id == region_id,
                Server.is_active.is_(True),
            )
        )
        server = server_result.scalar_one_or_none()

    if not server:
        async with async_session() as session:
            pending_result = await session.execute(
                select(TestPeriod).where(
                    TestPeriod.tg_id == tg_id,
                    TestPeriod.subscription == "trial_pending",
                )
            )
            pending_trial = pending_result.scalar_one_or_none()
            if pending_trial:
                await session.delete(pending_trial)
                await session.commit()
        await call.message.answer("❌ Сервер не найден или недоступен.")
        await call.answer()
        return

    try:
        file_path = await provision_client_wg(
            client_name,
            server_api_url(server),
            server.password,
        )
    except WireGuardCapacityError:
        logger.info(
            "Trial server reached capacity after reservation: tg_id=%s region=%s region_id=%s",
            tg_id,
            region,
            region_id,
        )
        async with async_session() as session:
            pending_result = await session.execute(
                select(TestPeriod).where(
                    TestPeriod.tg_id == tg_id,
                    TestPeriod.subscription == "trial_pending",
                )
            )
            pending_trial = pending_result.scalar_one_or_none()
            if pending_trial:
                await session.delete(pending_trial)
                await session.commit()
        await call.message.answer(
            "⚠️ На сервере закончились свободные места. Выберите другой сервер."
        )
        await call.answer()
        return
    except Exception:
        logger.exception(
            "Failed to provision trial: tg_id=%s client=%s region=%s region_id=%s",
            tg_id,
            client_name,
            region,
            region_id,
        )
        await call.message.answer(
            "⚠️ Не удалось выдать пробную конфигурацию. Попробуйте ещё раз через минуту "
            "или напишите в поддержку."
        )
        await call.answer()
        return

    async with async_session() as session:
        result = await session.execute(
            select(TestPeriod).where(TestPeriod.tg_id == tg_id)
        )
        stored_trial = result.scalar_one_or_none()
        if not stored_trial:
            logger.critical(
                "Trial reservation disappeared after WireGuard provisioning: tg_id=%s client=%s",
                tg_id,
                client_name,
            )
            await call.message.answer("⚠️ Пробный период требует ручной проверки.")
            await call.answer()
            return
        stored_trial.subscription = "trial"
        await session.commit()

    logger.info(
        "Trial activated: tg_id=%s trial_id=%s client=%s region=%s region_id=%s expiry=%s",
        tg_id,
        stored_trial.id,
        client_name,
        region,
        region_id,
        expiry_date,
    )
    await call.message.answer(texts_for_bot["TRIAL_ACTIVATED"], parse_mode="HTML")
    await call.message.answer_document(FSInputFile(file_path))
    await call.answer()
