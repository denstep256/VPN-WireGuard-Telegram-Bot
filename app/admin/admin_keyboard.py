from aiogram.types import (ReplyKeyboardMarkup, KeyboardButton,
                           InlineKeyboardMarkup, InlineKeyboardButton)

main_admin = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text='Купить 💳')],
                                     [KeyboardButton(text='Проверить подписку ✅')],
                                     [KeyboardButton(text='Как подключить ⚙️')],
                                     [KeyboardButton(text='Помощь 🆘'),
                                      KeyboardButton(text='О VPN ℹ️')],
                                     [KeyboardButton(text='Админ')]],
                           resize_keyboard=True)

admin_panel = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text='Рассылка'),
                                             KeyboardButton(text='Статистика')],
                                            [KeyboardButton(text='Добавить сервер')],
                                            [KeyboardButton(text='Администрирование подписок ')],
                                            [KeyboardButton(text='Назад (Админ)')]],
                           resize_keyboard=True)

stat_kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text='Клиенты на сервере'),
                                         KeyboardButton(text='Пользователи в боте')],
                                        [KeyboardButton(text='Пользователи с подпиской'),
                                         KeyboardButton(text='Пользователи с пробным периодом')],
                                        [KeyboardButton(text='Платежы')],
                                        [KeyboardButton(text='Назад Админ')]],
                           resize_keyboard=True)

send_kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text='Без фото')],
                                        [KeyboardButton(text='С фото')],
                                        [KeyboardButton(text='Назад Админ')]],

                           resize_keyboard=True)

preview_kb = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text='Да',
                          callback_data=f'confirm_broadcast')],
    [InlineKeyboardButton(text='Нет',
                          callback_data=f'cancel_broadcast')]])