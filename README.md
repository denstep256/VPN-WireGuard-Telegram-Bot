# Телеграм-бот для сервиса подписки на VPN 🚀

Это телеграм-бот, который управляет подписками на VPN, предоставляя пользователям доступ к VPN-файлам в зависимости от статуса их подписки. Бот отправляет уведомления пользователям за день до окончания подписки и управляет назначением VPN-файлов в зависимости от продления или истечения подписки. Также в боте встроена функция оплаты подписки через сервис Юкасса 💳.

## Особенности ✨

- **Управление подписками**: Пользователи могут подписаться на ежемесячную, полугодовую или годовую подписку 📅.
- **Назначение файлов**: После оплаты пользователи получают уникальный VPN-конфигурационный файл 💼.
- **Уведомления об истечении подписки**: Бот отправляет пользователю уведомление за день до окончания подписки ⏰.
- **Перераспределение файлов**: Если подписка не продлена, файл помечается как неиспользуемый и может быть передан другому пользователю 🔄.
- **Обработка продления**: При продлении подписки файл остаётся назначенным тому же пользователю 🔒.
- **Оплата через Юкасса**: Встроенная функция оплаты подписки через сервис Юкасса. Пользователи могут оплачивать подписку прямо через бота 💳.

## Технологии 📋

- Python 3.8+
- Telegram Bot API
- SQLAlchemy для управления базой данных
- SQLite3 (или другая БД в зависимости от конфигурации)
- Aiogram (асинхронное API для телеграм-ботов)
- VPN-конфигурационные файлы 🛠️
- Юкасса API для обработки платежей 💸

## Архитектура бота и БД

![Описание картинки](app/drawio.png)

## Установка 🔧

1. Клонируйте репозиторий
2. Устанавливаем WireGuard на сервер. Как это сделать: https://github.com/wg-easy/wg-easy/tree/production
3. Создайте в корне проекта файл config.py и поместите туда
```python
TOKEN='TELEGRAM'
DB_URL_USERS='sqlite+aiosqlite:///db.sqlite3'
DB_URL_KEYS='sqlite:///issued_keys.sqlite3'

PAYMENT_TOKEN='381764678:TEST:95145'

WG_API='rufvyh-keksam-fUcjo0'
WG_ADDRESS='http://147.45.174.189:51821'

ADMIN_ID='360395051'
```
4. Установите зависимости
```bash
pip install requirements.txt
```
5. Запустите бота
```bash
python main.py
```
