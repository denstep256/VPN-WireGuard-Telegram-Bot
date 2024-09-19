import asyncio

from aiogram import Bot

from aiogram.types import Message, CallbackQuery, LabeledPrice, PreCheckoutQuery, FSInputFile
from aiogram import Router, F
from datetime import datetime, timedelta

from sqlalchemy import select, delete, update

import config
from app.database.models import async_session, Static, Subscribers, Payments

from app.addons.utilits import calculate_expiry_date, check_available_clients_count, generate_client_name
from app.wg_api.wg_api import add_client_wg, get_config_wg

pay_router = Router()

@pay_router.callback_query(F.data.startswith('one_month'))
async def create_invoice(call: CallbackQuery):
    await call.bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)
    prices = [LabeledPrice(label='description', amount=199 * 100)]  # Сумма в копейках
    await call.bot.send_invoice(
        chat_id=call.from_user.id,
        title="Подписка",
        description='description',
        payload="subscription_monthly",
        provider_token=config.PAYMENT_TOKEN,
        currency="RUB",
        prices=prices,
        start_parameter="subscription",
        need_email=True,
        is_flexible=False,
        need_shipping_address=False
    )

@pay_router.callback_query(F.data.startswith('six_month'))
async def create_invoice(call: CallbackQuery):
    await call.bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)
    prices = [LabeledPrice(label='description', amount=999 * 10)]  # Сумма в копейках
    await call.bot.send_invoice(
        chat_id=call.from_user.id,
        title="Подписка",
        description='description',
        payload="subscription_semi_annual",
        provider_token=config.PAYMENT_TOKEN,
        currency="RUB",
        prices=prices,
        start_parameter="subscription",
        need_email=True,
        is_flexible=False,
        need_shipping_address=False
    )

@pay_router.callback_query(F.data.startswith('twelve_month'))
async def create_invoice(call: CallbackQuery):
    await call.bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)
    prices = [LabeledPrice(label='description', amount=1799 * 10)]  # Сумма в копейках
    await call.bot.send_invoice(
        chat_id=call.from_user.id,
        title="Подписка",
        description='description',
        payload="subscription_annual",
        provider_token=config.PAYMENT_TOKEN,
        currency="RUB",
        prices=prices,
        start_parameter="subscription",
        need_email=True,
        is_flexible=False,
        need_shipping_address=False
    )


@pay_router.pre_checkout_query()
async def process_pre_checkout_query(pre_checkout_query: PreCheckoutQuery, bot: Bot):
    # Проверка доступности файла конфигурации
    is_available = await check_available_clients_count()

    if is_available:
        # Разрешить продолжение процесса оплаты
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
            username = username,
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
            await session.commit()
            await message.answer(f'Ваша подписка успешно оформлена до {expiry_date}')
            # TODO: Написать здесь текст с благодарностью за приобретение подписки и дальше будет отправлен файл авторизации, мб придумать тоже какой-нибудь интересный текст

        else:
            # 2. Проверка наличия пользователя в таблице subscribers
            query = select(Subscribers).where(Subscribers.tg_id == tg_id)
            # query = await session.scalar(select(Subscribers.tg_id == tg_id))
            result = await session.execute(query)
            user_in_subscribers = result.scalar_one_or_none()

            if user_in_subscribers:
                #РАБОТАЕТ
                # 3. Продление подписки для существующего пользователя
                current_expiry_date = user_in_subscribers.expiry_date

                # Определение нового срока подписки в зависимости от payload
                if payload == 'subscription_monthly':
                    current_expiry_date = datetime.strptime(current_expiry_date,
                                                            "%Y-%m-%d")  # Укажи правильный формат даты
                    new_expiry_date = (current_expiry_date + timedelta(days=31)).date()
                elif payload == 'subscription_semi_annual':
                    current_expiry_date = datetime.strptime(current_expiry_date,
                                                            "%Y-%m-%d")
                    new_expiry_date = (current_expiry_date + timedelta(days=182)).date()  # полгода
                elif payload == 'subscription_annual':
                    current_expiry_date = datetime.strptime(current_expiry_date,
                                                            "%Y-%m-%d")
                    new_expiry_date = (current_expiry_date + timedelta(days=365)).date()

                # Обновляем срок подписки в базе данных
                user_in_subscribers.expiry_date = new_expiry_date
                await session.commit()
                await message.answer(f'Ваша подписка успешно продлена до {new_expiry_date}')
                #TODO: Здесь пользователь продлевает существующую подписку, после приобретения скинуть пользователю его файл конфигурации (Сначала сделать проверку из файлов на сервере, если там нет, то вытянуть с WG

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
                await session.commit()
                await message.answer(f'Ваша подписка успешно оформлена до {expiry_date}')
                #TODO: Написать здесь текст с благодарностью за приобретение подписки и дальше будет отправлен файл авторизации, мб придумать тоже какой-нибудь интересный текст

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
        else:
            # Формируем запрос для получения file_name по tg_id
            query = select(Subscribers.file_name).filter_by(tg_id=tg_id)
            result = await session.execute(query)
            file_name = result.scalar_one_or_none()  # Получаем одно значение или None, если не найдено

            file_path = f"app/auth/{file_name}.conf"  # Укажи правильный путь к файлу
            document = FSInputFile(file_path)
            await message.answer_document(document)


#TODO: После успешной оплаты, нужно удалить счет, который присылается create_invoice
#TODO: Посмотреть файл trial, найти там места где нужно вывести сообщение и написать там todo
#TODO: Вообще в целом посмотреть всю программу и написать todo там, где нужно написать красивый текст
#TODO: Текста по возможности писать ы text.json