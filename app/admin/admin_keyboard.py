from aiogram.types import (ReplyKeyboardMarkup, KeyboardButton)

main_admin = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text='Купить 💳')],
                                     [KeyboardButton(text='Проверить подписку ✅')],
                                     [KeyboardButton(text='Как подключить ⚙️')],
                                     [KeyboardButton(text='Помощь 🆘'),
                                      KeyboardButton(text='О VPN ℹ️')],
                                     [KeyboardButton(text='Админ')]],
                           resize_keyboard=True)

admin_panel = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text='Рассылка'),
                                             KeyboardButton(text='Статистика')],
                                            [KeyboardButton(text='Выдать подписку'),
                                             KeyboardButton(text='Бан')],
                                            [KeyboardButton(text='Назад (Админ)')]],
                           resize_keyboard=True)

stat_kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text='Клиенты на сервере'),
                                         KeyboardButton(text='Пользователи в боте')],
                                        [KeyboardButton(text='Пользователи с подпиской'),
                                        KeyboardButton(text='Пользователи с пробным периодом')],
                                        [KeyboardButton(text='Назад Админ')]],
                           resize_keyboard=True)

send_kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text='Без фото')],
                                        [KeyboardButton(text='С фото')],
                                        [KeyboardButton(text='Назад Админ')]],

                           resize_keyboard=True)