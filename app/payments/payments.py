import asyncio
import json

from aiogram import Bot

from aiogram.types import Message, CallbackQuery, LabeledPrice, PreCheckoutQuery, FSInputFile
from aiogram import Router, F
from datetime import datetime, timedelta

from sqlalchemy import select, delete, update

import config
from app.database.models import async_session, Static, Subscribers, Payments, User

from app.addons.utilits import calculate_expiry_date, check_available_clients_count, generate_client_name
from app.wg_api.wg_api import add_client_wg, get_config_wg

pay_router = Router()



@pay_router.callback_query(F.data.startswith('one_month'))
async def create_invoice(call: CallbackQuery):
    PROVIDER_DATA_WO_EMAIL_MONTH = {
        "receipt": {
            "items": [{
                "description": "Подписка на 1 месяц",
                "quantity": "1.00",
                "amount": {
                    "value": "199.00",
                    "currency": "RUB"
                },
                "vat_code": 1
            }]
        }
    }
    await call.bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)
    prices = [LabeledPrice(label='Подписка на 1 месяц', amount=199 * 100)]  # Сумма в копейках
    await call.bot.send_invoice(
        chat_id=call.from_user.id,
        title="Доступ к VPN на 1 мес.",
        description='Оплата картой в Telegram 💳. В поле электронная почта укажите СВОЮ почту, на неё придет ваш чек об оплате.',
        payload="monthly_subs",
        provider_token=config.PAYMENT_TOKEN,
        currency="RUB",
        prices=prices,
        start_parameter="subscription",
        need_email=True,
        send_email_to_provider=True,
        provider_data=json.dumps(PROVIDER_DATA_WO_EMAIL_MONTH),
    )



@pay_router.callback_query(F.data.startswith('six_month'))
async def create_invoice(call: CallbackQuery):
    PROVIDER_DATA_WO_EMAIL_SEMI = {
        "receipt": {
            "items": [{
                "description": "Подписка на 6 месяцев",
                "quantity": "1.00",
                "amount": {
                    "value": "999.00",
                    "currency": "RUB"
                },
                "vat_code": 1
            }]
        }
    }
    await call.bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)
    prices = [LabeledPrice(label='Подписка на 6 месяцев', amount=999 * 100)]  # Сумма в копейках
    await call.bot.send_invoice(
        chat_id=call.from_user.id,
        title="Доступ к VPN на 6 мес.",
        description='Оплата картой в Telegram 💳. В поле электронная почта укажите СВОЮ почту, на неё придет ваш чек об оплате.',
        payload="semi_annual_subs",
        provider_token=config.PAYMENT_TOKEN,
        currency="RUB",
        prices=prices,
        start_parameter="subscription",
        need_email=True,
        send_email_to_provider=True,
        provider_data=json.dumps(PROVIDER_DATA_WO_EMAIL_SEMI),
    )


@pay_router.callback_query(F.data.startswith('twelve_month'))
async def create_invoice(call: CallbackQuery):
    PROVIDER_DATA_WO_EMAIL_ANNUAL = {
        "receipt": {
            "items": [{
                "description": "Подписка на 12 месяцев",
                "quantity": "1.00",
                "amount": {
                    "value": "1799.00",
                    "currency": "RUB"
                },
                "vat_code": 1
            }]
        }
    }
    await call.bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)
    prices = [LabeledPrice(label='Подписка на 12 месяцев', amount=1799 * 100)]  # Сумма в копейках
    await call.bot.send_invoice(
        chat_id=call.from_user.id,
        title="Доступ к VPN на 12 мес.",
        description='Оплата картой в Telegram 💳. В поле электронная почта укажите СВОЮ почту, на неё придет ваш чек об оплате.',
        payload="annual_subs",
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
    async with async_session() as session:
        # Проверка, есть ли пользователь в базе данных Subscribers
        user_in_subscribers = await session.scalar(
            select(Subscribers).where(Subscribers.tg_id == pre_checkout_query.from_user.id)
        )

    if user_in_subscribers:
        # Если пользователь уже есть в таблице Subscribers, разрешить оплату
        await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)
    else:
        # Если пользователя нет в базе данных, проверяем доступные файлы
        is_available = await check_available_clients_count()

        if is_available:
            # Разрешить оплату, если доступные файлы есть
            await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)
        else:
            # Отклонить оплату, если файлы недоступны
            await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=False,
                                                error_message="К сожалению, нет доступных файлов конфигурации.")


@pay_router.message(F.successful_payment)
async def handle_successful_payment(message: Message):
    async with async_session() as session:
        tg_id = message.from_user.id
        username = message.from_user.username
        payload = message.successful_payment.invoice_payload
        summa = message.successful_payment.total_amount / 100
        provider_payment_charge_id = message.successful_payment.provider_payment_charge_id

        new_payment = Payments(
            tg_id=tg_id,
            username=username,
            summa=summa,
            time_to_add=datetime.now(),
            payload=payload,
            provider_payment_charge_id=provider_payment_charge_id
        )
        session.add(new_payment)
        await session.commit()

        #РАБОТАЕТ
        # 1. Проверка наличия пользователя в таблице static
        query = select(Static).where(Static.tg_id == tg_id)
        # query = await session.scalar(select(Static.tg_id == tg_id))
        result = await session.execute(query)
        user_in_static = result.scalar_one_or_none()

        if user_in_static:
            # Если пользователь есть в таблице static, удаляем его запись
            delete_query = delete(Static).where(Static.tg_id == tg_id)
            # delete_query = await session.delete(select(Static.tg_id == tg_id))
            await session.execute(delete_query)
            await session.commit()

            # Определение срока подписки в зависимости от payload
            expiry_date = await calculate_expiry_date(payload)

            # Добавление пользователя в таблицу subscribers
            new_subscriber = Subscribers(
                tg_id=tg_id,
                username=username,
                file_name='check',
                subscription=payload,
                expiry_date=expiry_date,
                notif_oneday=False
            )
            session.add(new_subscriber)

            user = await session.execute(
                select(User).filter_by(tg_id=tg_id)
            )
            user = user.scalar_one_or_none()

            if user:
                user.is_active_subs = True
                user.use_subs = True
                session.add(user)
            await session.commit()

            await message.answer(f'Ваша подписка успешно оформлена и будет действовать до {expiry_date}.\n\nВаш файл авторизации будет отправлен вам в следующем сообщении. Также вы можете найти его в главном меню, нажав на кнопку <b>«Проверить подписку»</b>.\n\nБлагодарим вас за доверие! ❤️', parse_mode="HTML")


        else:
            # 2. Проверка наличия пользователя в таблице subscribers и is_active_subs == True
            query = select(Subscribers).where(Subscribers.tg_id == tg_id)
            result = await session.execute(query)
            user_in_subscribers = result.scalar_one_or_none()

            query_is_active_subs = select(User).where(User.is_active_subs == True, User.tg_id == tg_id)
            result_subs = await session.execute(query_is_active_subs)
            user_is_active_subs = result_subs.scalar_one_or_none()

            # Проверка наличия пользователя в таблице subscribers и у него is_active_subs == True в таблице User
            # query = (
            #     select(Subscribers)
            #     .join(User)  # Объединяем таблицы Subscribers и User
            #     .where(Subscribers.tg_id == tg_id, User.is_active_subs == True)
            # )
            # result = await session.execute(query)
            # user_in_subscribers_with_active_subs = result.scalar_one_or_none()

            if user_in_subscribers and user_is_active_subs:
                #РАБОТАЕТ
                # 3. Продление подписки для существующего пользователя
                current_expiry_date = user_in_subscribers.expiry_date

                # Определение нового срока подписки в зависимости от payload
                if payload == 'monthly_subs':
                    current_expiry_date = datetime.strptime(current_expiry_date,
                                                            "%Y-%m-%d")  # Укажи правильный формат даты
                    new_expiry_date = (current_expiry_date + timedelta(days=31)).date()
                elif payload == 'semi_annual_subs':
                    current_expiry_date = datetime.strptime(current_expiry_date,
                                                            "%Y-%m-%d")
                    new_expiry_date = (current_expiry_date + timedelta(days=182)).date()  # полгода
                elif payload == 'annual_subs':
                    current_expiry_date = datetime.strptime(current_expiry_date,
                                                            "%Y-%m-%d")
                    new_expiry_date = (current_expiry_date + timedelta(days=365)).date()

                # Обновляем срок подписки в базе данных
                user_in_subscribers.expiry_date = new_expiry_date
                user_in_subscribers.notif_oneday = False
                user_in_subscribers.note = ' '
                user_in_subscribers.subscription = payload
                await session.commit()
                await message.answer(f'Ваша подписка успешно продлена до {new_expiry_date}.\nБлагодарим вас за доверие! ❤️', parse_mode="HTML")

            else:
                #РАБОТАЕТ
                # 4. Добавление нового пользователя в таблицу subscribers
                # Определение срока подписки в зависимости от payload
                expiry_date = await calculate_expiry_date(payload)

                # Добавление пользователя в таблицу subscribers
                new_subscriber = Subscribers(
                    tg_id=tg_id,
                    username=username,
                    file_name='check',
                    subscription=payload,
                    expiry_date=expiry_date,
                    notif_oneday=False
                )
                session.add(new_subscriber)

                user = await session.execute(
                    select(User).filter_by(tg_id=tg_id)
                )
                user = user.scalar_one_or_none()

                if user:
                    user.is_active_subs = True
                    user.use_subs = True
                    session.add(user)
                await session.commit()

                await message.answer(f'Ваша подписка успешно оформлена и будет действовать до {expiry_date}.\n\nВаш файл авторизации будет отправлен вам в следующем сообщении. Также вы можете найти его в главном меню, нажав на кнопку <b>«Проверить подписку»</b>.\n\nБлагодарим вас за доверие! ❤️', parse_mode="HTML")


        query = select(Subscribers).filter_by(file_name='check', tg_id=tg_id)
        result = await session.execute(query)
        subscriber = result.scalars().first()  # Используем first(), чтобы получить первый (и в данном случае единственный) объект

        if subscriber:
            client_name = generate_client_name()
            await add_client_wg(client_name)
            await get_config_wg(client_name)
            await asyncio.sleep(1)
            file_path = f"app/auth/{client_name}.conf"  # Укажи правильный путь к файлу
            document = FSInputFile(file_path)
            await message.answer_document(document)

            update_query = (
                update(Subscribers)
                .where(Subscribers.tg_id == tg_id)
                .values(file_name=client_name)
            )
            await session.execute(update_query)
            await session.commit()
            #Возвращаем файл конфигурации при продлении подписки
        else:
            # Формируем запрос для получения file_name по tg_id
            query = select(Subscribers.file_name).filter_by(tg_id=tg_id)
            result = await session.execute(query)
            file_name = result.scalar_one_or_none()  # Получаем одно значение или None, если не найдено

            file_path = f"app/auth/{file_name}.conf"  # Укажи правильный путь к файлу
            document = FSInputFile(file_path)
            await message.answer_document(document)