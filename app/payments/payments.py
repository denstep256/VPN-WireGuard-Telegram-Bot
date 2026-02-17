import asyncio
import json

from aiogram import Bot

from aiogram.types import Message, CallbackQuery, LabeledPrice, PreCheckoutQuery, FSInputFile
from aiogram import Router, F
from datetime import datetime

from sqlalchemy import select, update

import config
from config import one_mounth_price, six_mounth_price, twelve_mounth_price
from app.database.models import async_session, Subscribers, Payments, User, Server

from app.addons.utilits import calculate_expiry_date, check_available_clients_count, generate_client_name
from app.wg_api.wg_api import add_client_wg, get_config_wg

pay_router = Router()



@pay_router.callback_query(F.data.startswith('one_month|'))
async def create_invoice_one_month(call: CallbackQuery):
    parts = call.data.split("|")
    if len(parts) < 3:
        await call.answer("❌ Ошибка данных.", show_alert=True)
        return

    plan, region, region_id_str = parts[0], parts[1], parts[2]
    if not region_id_str.isdigit():
        await call.answer("⚠️ Некорректный ID сервера.", show_alert=True)
        return
    region_id = int(region_id_str)

    payload = f"monthly_subs|{region}|{region_id}"

    PROVIDER_DATA_WO_EMAIL_MONTH = {
        "receipt": {
            "items": [{
                "description": "Подписка на 1 месяц",
                "quantity": "1.00",
                "amount": {
                    "value": f"{one_mounth_price}.00",
                    "currency": "RUB"
                },
                "vat_code": 1
            }]
        }
    }
    await call.bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)
    prices = [LabeledPrice(label='Подписка на 1 месяц', amount=one_mounth_price * 100)]  # Сумма в копейках
    await call.bot.send_invoice(
        chat_id=call.from_user.id,
        title="Доступ к VPN на 1 мес.",
        description='Оплата картой в Telegram 💳. В поле электронная почта укажите СВОЮ почту, на неё придет ваш чек об оплате.',
        payload=payload,
        provider_token=config.PAYMENT_TOKEN,
        currency="RUB",
        prices=prices,
        start_parameter="subscription",
        need_email=True,
        send_email_to_provider=True,
        provider_data=json.dumps(PROVIDER_DATA_WO_EMAIL_MONTH),
    )



@pay_router.callback_query(F.data.startswith('six_month|'))
async def create_invoice(call: CallbackQuery):
    parts = call.data.split("|")
    if len(parts) < 3:
        await call.answer("❌ Ошибка данных.", show_alert=True)
        return

    plan, region, region_id_str = parts[0], parts[1], parts[2]
    if not region_id_str.isdigit():
        await call.answer("⚠️ Некорректный ID сервера.", show_alert=True)
        return
    region_id = int(region_id_str)

    payload = f"semi_annual_subs|{region}|{region_id}"

    PROVIDER_DATA_WO_EMAIL_SEMI = {
        "receipt": {
            "items": [{
                "description": "Подписка на 6 месяцев",
                "quantity": "1.00",
                "amount": {
                    "value": f"{six_mounth_price}.00",
                    "currency": "RUB"
                },
                "vat_code": 1
            }]
        }
    }
    await call.bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)
    prices = [LabeledPrice(label='Подписка на 6 месяцев', amount=six_mounth_price * 100)]  # Сумма в копейках
    await call.bot.send_invoice(
        chat_id=call.from_user.id,
        title="Доступ к VPN на 6 мес.",
        description='Оплата картой в Telegram 💳. В поле электронная почта укажите СВОЮ почту, на неё придет ваш чек об оплате.',
        payload=payload,
        provider_token=config.PAYMENT_TOKEN,
        currency="RUB",
        prices=prices,
        start_parameter="subscription",
        need_email=True,
        send_email_to_provider=True,
        provider_data=json.dumps(PROVIDER_DATA_WO_EMAIL_SEMI),
    )


@pay_router.callback_query(F.data.startswith('twelve_month|'))
async def create_invoice(call: CallbackQuery):
    parts = call.data.split("|")
    if len(parts) < 3:
        await call.answer("❌ Ошибка данных.", show_alert=True)
        return

    plan, region, region_id_str = parts[0], parts[1], parts[2]
    if not region_id_str.isdigit():
        await call.answer("⚠️ Некорректный ID сервера.", show_alert=True)
        return
    region_id = int(region_id_str)

    payload = f"annual_subs|{region}|{region_id}"

    PROVIDER_DATA_WO_EMAIL_ANNUAL = {
        "receipt": {
            "items": [{
                "description": "Подписка на 12 месяцев",
                "quantity": "1.00",
                "amount": {
                    "value": f"{twelve_mounth_price}.00",
                    "currency": "RUB"
                },
                "vat_code": 1
            }]
        }
    }
    await call.bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)
    prices = [LabeledPrice(label='Подписка на 12 месяцев', amount=twelve_mounth_price * 100)]  # Сумма в копейках
    await call.bot.send_invoice(
        chat_id=call.from_user.id,
        title="Доступ к VPN на 12 мес.",
        description='Оплата картой в Telegram 💳. В поле электронная почта укажите СВОЮ почту, на неё придет ваш чек об оплате.',
        payload=payload,
        provider_token=config.PAYMENT_TOKEN,
        currency="RUB",
        prices=prices,
        start_parameter="subscription",
        need_email=True,
        send_email_to_provider=True,
        provider_data=json.dumps(PROVIDER_DATA_WO_EMAIL_ANNUAL),
    )


@pay_router.pre_checkout_query()
async def process_pre_checkout_query(pre_checkout_query: PreCheckoutQuery, bot: Bot):
    # Получаем payload из запроса
    payload = pre_checkout_query.invoice_payload
    parts = payload.split("|")

    if len(parts) >= 3:
        base_plan, region, region_id_str = parts[0], parts[1], parts[2]
        if region_id_str.isdigit():
            region_id = int(region_id_str)
        else:
            region_id = None
    else:
        region = None
        region_id = None

    is_available = await check_available_clients_count(region=region, region_id=region_id)

    if is_available:
        await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)
    else:
        await bot.answer_pre_checkout_query(
            pre_checkout_query.id,
            ok=False,
            error_message="К сожалению, нет доступных файлов конфигурации на выбранном сервере."
        )

@pay_router.message(F.successful_payment)
async def handle_successful_payment(message: Message):
    payload = message.successful_payment.invoice_payload
    parts = payload.split("|")
    if len(parts) < 3:
        await message.answer("❌ Некорректный payload платежа.")
        return
    base_payload, region, region_id_str = parts[0], parts[1], parts[2]
    region_id = int(region_id_str)

    async with async_session() as session:
        tg_id = message.from_user.id
        username = message.from_user.username or "unknown"
        price = message.successful_payment.total_amount / 100
        provider_payment_charge_id = message.successful_payment.provider_payment_charge_id

        new_payment = Payments(
            tg_id=tg_id,
            username=username or "unknown",
            price=price,
            date=datetime.now(),
            tarific_plan=base_payload,
            provider_payment_charge_id=provider_payment_charge_id
        )
        session.add(new_payment)
        await session.commit()

        expiry_date = await calculate_expiry_date(base_payload)
        client_name = generate_client_name()

        new_subscriber = Subscribers(
            tg_id=tg_id,
            username=username or "unknown",
            file_name='check',  # временно
            subscription=base_payload,
            expiry_date=expiry_date,
            server_region=region,
            server_region_id=region_id,
            notif_oneday=False
        )
        session.add(new_subscriber)
        await session.flush()

        result = await session.execute(
            select(Server).where(
                Server.region == region,
                Server.region_id == region_id,
                Server.is_active == True
            )
        )
        server = result.scalar_one_or_none()

        if not server:
            await message.answer(f'Сервер не найден', parse_mode="HTML")

        host = server.host_ip
        port = server.port
        ip = f"http://{host}:{port}"
        password = server.password

        await add_client_wg(client_name, ip, password)
        await get_config_wg(client_name, ip, password)
        await asyncio.sleep(1)

        file_path = f"app/auth/{client_name}.conf"
        document = FSInputFile(file_path)

        await session.execute(
            update(Subscribers)
            .where(Subscribers.id == new_subscriber.id)
            .values(file_name=client_name)
        )
        await session.commit()

        await message.answer(
            f'✅ Ваша подписка успешно оформлена до <b>{expiry_date}</b>.\n\n'
            f'Сервер: <b>{region} №{region_id}</b>\n\n'
            f'Файл конфигурации прикреплён ниже. Сохраните его!',
            parse_mode="HTML"
        )
        await message.answer_document(document)