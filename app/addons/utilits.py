import os


from datetime import timedelta, datetime, date
import random
from sqlalchemy import select

from app.database.models import async_session, Subscribers, Server
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

async def check_available_clients_count(region: str = None, region_id: int = None) -> bool:
    async with async_session() as session:
        result = await session.execute(
            select(Server).where(
                Server.region == region,
                Server.region_id == region_id,
                Server.is_active == True
            )
        )
        server = result.scalar_one_or_none()

        if not server:
            return False  # Сервер не найден → слоты недоступны

        # Получаем параметры (если понадобятся позже, например для логгирования или ограничений)
        host = server.host_ip
        port = server.port
        ip = f"https://{host}:{port}"
        password = server.password
        count = await get_client_count_wg(ip, password)

        if count < 60:
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


async def get_active_subscriptions(tg_id: int):
    today = datetime.now().date().isoformat()
    async with async_session() as session:
        result = await session.execute(
            select(Subscribers).where(
                Subscribers.tg_id == tg_id,
                Subscribers.expiry_date >= today
            )
        )
        return result.scalars().all()

def format_tariff(tariff_code: str) -> str:
    tariff_map = {
        "monthly_subs": "1 месяц",
        "semi_annual_subs": "6 месяцев",
        "annual_subs": "12 месяцев",
    }
    return tariff_map.get(tariff_code, tariff_code)  # если вдруг новый тариф — покажет как есть

def add_months(d: date, months: int) -> date:
    # простой безопасный add_months без внешних библиотек
    year = d.year + (d.month - 1 + months) // 12
    month = (d.month - 1 + months) % 12 + 1

    # последний день месяца
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    last_day = (next_month - timedelta(days=1)).day

    day = min(d.day, last_day)
    return date(year, month, day)


PLAN_TO_MONTHS = {
    "monthly_subs": 1,
    "semi_annual_subs": 6,
    "annual_subs": 12,
}
