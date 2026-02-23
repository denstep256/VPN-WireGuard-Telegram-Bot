import asyncio
from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.types import CallbackQuery, FSInputFile
from sqlalchemy import exists, select

from app.addons.utilits import check_available_clients_count, generate_client_name
from app.database.models import Server, TestPeriod, async_session
from app.users.handlers import texts_for_bot
from app.wg_api.wg_api import add_client_wg, get_config_wg

trial_router = Router()


def _parse_trial_callback(data: str) -> tuple[str | None, int | None]:
    parts = (data or "").split("|")
    if len(parts) < 3 or parts[0] != "test_3_days":
        return None, None
    region = parts[1]
    if not parts[2].isdigit():
        return None, None
    return region, int(parts[2])


async def _is_trial_used(tg_id: int) -> bool:
    async with async_session() as session:
        return bool(await session.scalar(select(exists().where(TestPeriod.tg_id == tg_id))))


@trial_router.callback_query(F.data.startswith("test_3_days|"))
async def trial_button(call: CallbackQuery):
    region, region_id = _parse_trial_callback(call.data)
    if not region or region_id is None:
        await call.answer("❌ Некорректные данные сервера.", show_alert=True)
        return

    if await _is_trial_used(call.from_user.id):
        await call.message.answer(texts_for_bot.get("TRIAL_ALREADY_USED"), parse_mode="HTML")
        await call.answer()
        return

    available_conf = await check_available_clients_count(region=region, region_id=region_id)
    if not available_conf:
        await call.message.answer(
            "⚠️ На выбранном сервере сейчас нет свободных мест для пробного периода. Попробуйте другой сервер.",
            parse_mode="HTML",
        )
        await call.answer()
        return

    async with async_session() as session:
        server_result = await session.execute(
            select(Server).where(
                Server.region == region,
                Server.region_id == region_id,
                Server.is_active == True,  # noqa: E712
            )
        )
        server = server_result.scalar_one_or_none()
        if not server:
            await call.message.answer("❌ Сервер не найден или недоступен.")
            await call.answer()
            return

    client_name = generate_client_name()
    expiry_date = (datetime.now() + timedelta(days=3)).date().isoformat()

    try:
        server_url = f"https://{server.host_ip}:{server.port}"
        await add_client_wg(client_name, server_url, server.password)
        await get_config_wg(client_name, server_url, server.password)
        await asyncio.sleep(1)
    except Exception:
        await call.message.answer(
            "⚠️ Не удалось выдать пробную конфигурацию. Попробуйте ещё раз через минуту или напишите в поддержку."
        )
        await call.answer()
        return

    async with async_session() as session:
        session.add(
            TestPeriod(
                tg_id=call.from_user.id,
                username=call.from_user.username or "unknown",
                file_name=client_name,
                subscription="trial",
                expiry_date=expiry_date,
                notif_oneday=False,
            )
        )
        await session.commit()

    await call.message.answer(texts_for_bot.get("TRIAL_ACTIVATED"), parse_mode="HTML")
    await call.message.answer_document(FSInputFile(f"app/auth/{client_name}.conf"))
    await call.answer()
