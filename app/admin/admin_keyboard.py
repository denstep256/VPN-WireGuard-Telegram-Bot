from aiogram.types import (ReplyKeyboardMarkup, KeyboardButton,
                           InlineKeyboardMarkup, InlineKeyboardButton)

main_admin = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text='Купить')],
                                     [KeyboardButton(text='Проверить подписку')],
                                     [KeyboardButton(text='Как подключить')],
                                     [KeyboardButton(text='Помощь'),
                                      KeyboardButton(text='О VPN')],
                                     [KeyboardButton(text='Админ')]],
                           resize_keyboard=True)

admin_panel = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text='Рассылка'),
                                             KeyboardButton(text='Бан')],
                                            [KeyboardButton(text='Выдать подписку'),
                                             KeyboardButton(text='Неактивные')],
                                            [KeyboardButton(text='Пользователи с подпиской'),
                                            KeyboardButton(text='Пользователи с пробным периодом')],
                                            [KeyboardButton(text='Назад (Админ)')]],
                           resize_keyboard=True)

