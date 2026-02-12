from aiogram.types import (ReplyKeyboardMarkup, KeyboardButton,
                           InlineKeyboardMarkup, InlineKeyboardButton)
from sqlalchemy import select

from sqlalchemy.orm import Session

from app.database.models import Server, Subscribers


def get_subscriptions_kb(subs: list[Subscribers]) -> InlineKeyboardMarkup:
    buttons = []
    for sub in subs:
        # Например: "Amsterdam №1 — до 2025-08-15"
        text = f"{sub.server_region} №{sub.server_region_id} — до {sub.expiry_date}"
        callback_data = f"renew_sub|{sub.id}"  # используем ID записи
        buttons.append([InlineKeyboardButton(text=text, callback_data=callback_data)])

    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

async def get_servers_keyboard(session: Session) -> InlineKeyboardMarkup:
    # Получаем активные серверы из БД
    result = await session.execute(
        select(Server).where(Server.is_active == True).order_by(Server.region)
    )
    servers = result.scalars().all()

    # Формируем кнопки
    buttons = []
    for server in servers:
        button_text = f"{server.region} №{server.region_id}"
        buttons.append([
            InlineKeyboardButton(
                text=button_text,
                callback_data=f'{server.region}-{server.region_id}'
            )
        ])

    # Если серверов нет — показываем уведомление
    if not buttons:
        buttons.append([
            InlineKeyboardButton(
                text="⚠️ Нет доступных серверов",
                callback_data='no_servers'
            )
        ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

main = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text='Купить 💳')],
                                     [KeyboardButton(text='Проверить подписку ✅')],
                                     [KeyboardButton(text='Как подключить ⚙️')],
                                     [KeyboardButton(text='Помощь 🆘'),
                                      KeyboardButton(text='О VPN ℹ️')]],
                           resize_keyboard=True)


help_kb = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text='Написать',
                          url="https://t.me/ZenithVPN_support",
                          callback_data='help_button')]])

def get_buy_kb(region: str, region_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text='Подписка на 1 месяц',
            callback_data=f'one_month|{region}|{region_id}'
        )],
        [InlineKeyboardButton(
            text='Подписка на 6 месяцев',
            callback_data=f'six_month|{region}|{region_id}'
        )],
        [InlineKeyboardButton(
            text='Подписка на 12 месяцев',
            callback_data=f'twelve_month|{region}|{region_id}'
        )],
        [InlineKeyboardButton(
            text='Пробная подписка на 3 дня',
            callback_data=f'test_3_days|{region}|{region_id}'
        )]
    ])

confirm_order_kb = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text='Написать',
                          url="https://t.me/ZenithVPN_support",
                          callback_data='confirm_order_kb')]])

how_to_connect_kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text='iPhone 📱')],
                                                  [KeyboardButton(text='Android 📱')],
                                                  [KeyboardButton(text='Скачал✅')],
                                                  [KeyboardButton(text='Назад ↩️')]],
                             resize_keyboard=True)

iphone_kb = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text='СКАЧАТЬ',
                          url="https://apps.apple.com/ru/app/wireguard/id1441195209",
                          callback_data='iph_kb')]])

android_kb = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text='СКАЧАТЬ',
                          url="https://play.google.com/store/apps/details?id=com.wireguard.android&pcampaignid=web_share",
                          callback_data='and_kb')]])

download_kb = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text='Инструкция для iPhone',
                          url="https://teletype.in/@zenithvpn/ogi7tHwL4qV",
                          callback_data='instruct_iph')],
    [InlineKeyboardButton(text='Инструкция для Android',
                          url='https://teletype.in/@zenithvpn/N1lyKcbCMeV',
                          callback_data='instruct_and')],
    [InlineKeyboardButton(text='Проверить VPN',
                          url='https://2ip.ru',
                          callback_data='check_bt')]])