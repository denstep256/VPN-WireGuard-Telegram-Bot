from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy import exists, select

from app.addons.utilits import check_available_clients_count, generate_client_name
from app.database.models import Server, TestPeriod, async_session
from app.users.handlers import texts_for_bot
from app.vpn.provisioning import (
    PROTOCOL_WIREGUARD,
    create_vpn_access,
    send_access_to_user,
)

trial_router = Router()


def _parse_trial_callback(data: str) -> tuple[str | None, str | None, int | None]:
    parts = (data or "").split("|")
    if len(parts) < 3 or parts[0] != "test_3_days":
        return None, None, None

    if len(parts) >= 4 and parts[1] in {"wireguard", "xui"}:
        protocol, region, region_id_str = parts[1], parts[2], parts[3]
    else:
        protocol, region, region_id_str = PROTOCOL_WIREGUARD, parts[1], parts[2]

    if not region_id_str.isdigit():
        return None, None, None
    return protocol, region, int(region_id_str)


async def _is_trial_used(tg_id: int) -> bool:
    async with async_session() as session:
        return bool(await session.scalar(select(exists().where(TestPeriod.tg_id == tg_id))))


@trial_router.callback_query(F.data.startswith("test_3_days|"))
async def trial_button(call: CallbackQuery):
    protocol, region, region_id = _parse_trial_callback(call.data)
    if not protocol or not region or region_id is None:
        await call.answer("❌ Некорректные данные сервера.", show_alert=True)
        return

    if await _is_trial_used(call.from_user.id):
        await call.message.answer(texts_for_bot.get("TRIAL_ALREADY_USED"), parse_mode="HTML")
        await call.answer()
        return

    try:
        available_conf = await check_available_clients_count(region=region, region_id=region_id, protocol=protocol)
    except Exception:
        available_conf = False

    if not available_conf:
        await call.message.answer(
            "⚠️ Выбранный VPN-сервис сейчас недоступен для пробного периода. Попробуйте другой вариант.",
            parse_mode="HTML",
        )
        await call.answer()
        return

    server = None
    if protocol == PROTOCOL_WIREGUARD:
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
        access = await create_vpn_access(
            protocol=protocol,
            client_name=client_name,
            expiry_date=expiry_date,
            tg_id=call.from_user.id,
            username=call.from_user.username or "unknown",
            server=server,
        )
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
                protocol=protocol,
                xui_sub_id=access.xui_sub_id,
                notif_oneday=False,
            )
        )
        await session.commit()

    await call.message.answer(texts_for_bot.get("TRIAL_ACTIVATED"), parse_mode="HTML")
    await send_access_to_user(call.message, access)
    await call.answer()
