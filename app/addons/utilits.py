import os


from datetime import timedelta, datetime
import random

from app.wg_api.wg_api import get_client_count_wg


# Глобальная переменная для хранения уникальных имен
generated_usernames = set()


def generate_client_name() -> str:
    """
    Генерирует уникальное имя пользователя в формате 'ZENITH-XXXXXX',
    где XXXXXX — случайная шестизначная последовательность цифр.

    :return: Уникальное сгенерированное имя пользователя
    """
    while True:
        random_digits = random.randint(100000, 999999)  # Генерируем шестизначное число
        client_name = f"ZENITH-{random_digits}"
        if client_name not in generated_usernames:  # Проверка на уникальность
            generated_usernames.add(client_name)  # Сохранение уникального имени
            return client_name

async def check_available_clients_count() -> bool:
    count = await get_client_count_wg()
    # Проверка количества клиентов
    if count < 253:
        return True
    else:
        return False

def delete_file_by_name(client_name: str):
    file_path = f"app/auth/{client_name}.conf"

    # Проверка на существование файла и его удаление
    if os.path.exists(file_path):
        os.remove(file_path)
    #     print(f"Файл {client_name} удален.")
    # else:
    #     print(f"Файл {client_name} не найден.")


async def calculate_expiry_date(payload):
    if payload == 'monthly_subs':
        expiry_date_month = datetime.now() + timedelta(days=31)
        return expiry_date_month.date()
    elif payload == 'semi_annual_subs':
        expiry_date_semi = datetime.now() + timedelta(days=182)
        return expiry_date_semi.date()
    elif payload == 'annual_subs':
        expiry_date_annual = datetime.now() + timedelta(days=365)
        return expiry_date_annual.date()
    else:
        raise ValueError("Invalid subscription duration")

def determine_subscription_type(days):
    if days < 31:
        return "less_month"
    elif days > 31:
        return "more_month"
    elif 31 < days < 181:
        return "less_annual"
    else:
        return "more_annual"
