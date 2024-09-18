from aiogram.types import (ReplyKeyboardMarkup, KeyboardButton,
                           InlineKeyboardMarkup, InlineKeyboardButton)


main = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text='Купить')],
                                     [KeyboardButton(text='Проверить подписку')],
                                     [KeyboardButton(text='Как подключить')],
                                     [KeyboardButton(text='Помощь'),
                                      KeyboardButton(text='О VPN')]],
                           resize_keyboard=True)


help_kb = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text='Написать',
                          url="https://t.me/ZenithVPN_support",
                          callback_data='help_button')]])

buy_kb = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text='Подписка на 1 месяц',
                          callback_data=f'one_month')],
    [InlineKeyboardButton(text='Подписка на 6 месяцев',
                          callback_data=f'six_month')],
    [InlineKeyboardButton(text='Подписка на 12 месяцев',
                          callback_data=f'twelve_month')],
    [InlineKeyboardButton(text='Пробная подписка на 7 дней',
                          callback_data=f'test_7_days')]])

confirm_order_kb = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text='Написать',
                          url="https://t.me/ZenithVPN_support",
                          callback_data='confirm_order_kb')]])

how_to_connect_kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text='iPhone')],
                                                  [KeyboardButton(text='Android')],
                                                  [KeyboardButton(text='Скачал✅')],
                                                  [KeyboardButton(text='Назад')]],
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


