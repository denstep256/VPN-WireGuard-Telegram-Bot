from aiogram import Bot

from aiogram.types import Message, CallbackQuery, LabeledPrice, PreCheckoutQuery, FSInputFile
from aiogram import Router, F
from datetime import datetime

import config
from app.payments.models import IssuedKey, SubscriptionDuration
from app.payments.requests import get_db, issue_file, get_available_files
from app.payments.common import get_file_path, check_file_exists
from app.addons.utilits import calculate_expiry_date

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

    try:
        db = next(get_db())
    except Exception as e:
        # Логирование ошибки при подключении к базе данных
        print(f"Database error: {e}")
        await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=False, error_message="Ошибка базы данных.")
        return

    try:
        # Получите доступные файлы
        available_files = get_available_files(db)

        if not available_files:
            # Если файлов нет, отмените запрос на оплату и уведомите пользователя
            await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=False,
                                                error_message="Извините, ключи больше не доступны.")
            return

        # Если все в порядке, подтвердите запрос
        await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)
    except Exception as e:
        # Логирование ошибки при обработке предварительного оформления заказа
        print(f"Pre-checkout error: {e}")
        await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=False, error_message="Ошибка при проверке заказа.")


@pay_router.message(F.successful_payment)
async def handle_successful_payment(message: Message, bot: Bot):
    user_id = message.from_user.id
    payload = message.successful_payment.invoice_payload
    duration_map = {
        "subscription_monthly": SubscriptionDuration.MONTHLY,
        "subscription_semi_annual": SubscriptionDuration.SEMI_ANNUAL,
        "subscription_annual": SubscriptionDuration.ANNUAL
    }

    duration = duration_map.get(payload, SubscriptionDuration.MONTHLY)

    db = next(get_db())
    available_files = get_available_files(db)

    if not available_files:
        await bot.send_message(chat_id=message.chat.id, text="Извините, ключи больше не доступны.")
        return

    current_subscription = db.query(IssuedKey).filter(IssuedKey.user_id == user_id).first()

    if current_subscription:
        new_expiry_date = calculate_expiry_date(current_subscription.expiry_date, duration)
        db.query(IssuedKey).filter(IssuedKey.user_id == user_id).update({
            IssuedKey.expiry_date: new_expiry_date,
            IssuedKey.is_used: True
        })
        db.commit()
        await bot.send_message(
            chat_id=message.chat.id,
            text=f"Ваша подписка продлена. Она будет действовать до {new_expiry_date.strftime('%d-%m-%Y')}."
        )
    else:
        file_name = available_files.pop()
        file_path = get_file_path(file_name)

        if not check_file_exists(file_path):
            await bot.send_message(chat_id=message.chat.id, text="Файл не найден.")
            return

        expiry_date = calculate_expiry_date(datetime.now(), duration)
        issue_file(db, user_id, file_name, duration)

        await bot.send_message(
            chat_id=message.chat.id,
            text=f"Привет! Ваш файл. Ваша подписка активна до {expiry_date.strftime('%d-%m-%Y')}."
        )
        await message.answer_document(document=FSInputFile(path=file_path))

