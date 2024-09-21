import aiohttp
import os
from wg_easy_api_wrapper.server import Server
from wg_easy_api_wrapper.errors import AlreadyLoggedInError
from config import WG_API, WG_ADDRESS

async def add_client_wg(client_name: str):
    url = WG_ADDRESS
    password = WG_API

    async with aiohttp.ClientSession() as session:
        server = Server(url, password, session)

        # Авторизация
        await authorize(server)

        # Добавление клиента
        await add_client(server, client_name)


async def get_config_wg(client_name: str):
    url = WG_ADDRESS
    password = WG_API

    async with aiohttp.ClientSession() as session:
        server = Server(url, password, session)

        # Авторизация
        await authorize(server)
        # Получение конфигурации клиента
        config = await save_client_configuration(server, client_name)
        if config:
            print(config)


async def remove_client_wg(client_name: str):
    url = WG_ADDRESS
    password = WG_API

    async with aiohttp.ClientSession() as session:
        server = Server(url, password, session)

        # Авторизация
        await authorize(server)
        # Удаление клиента
        await remove_client_by_name(server, client_name)

async def get_client_count_wg():
    url = WG_ADDRESS
    password = WG_API

    async with aiohttp.ClientSession() as session:
        server = Server(url, password, session)

        # Авторизация
        await authorize(server)
        # Получение количества клиентов
        count = await get_client_count(server)
        return count

async def authorize(server: Server) -> None:
    """
    Авторизует пользователя на сервере wg-easy.
    """
    try:
        await server.login()
        print("Успешно авторизован!")
    except AlreadyLoggedInError:
        print("Уже авторизован!")
    except Exception as e:
        print(f"Ошибка авторизации: {e}")

async def remove_client_by_name(server: Server, client_name: str) -> None:
    """
    Удаляет клиента по его имени.

    :param server: Экземпляр сервера
    :param client_name: Имя клиента для удаления
    """
    try:
        # Получаем список всех клиентов
        clients = await server.get_clients()

        # Ищем клиента по имени
        client_to_remove = None
        for client in clients:
            if client.name == client_name:
                client_to_remove = client
                break

        if client_to_remove:
            # Удаляем клиента по его UID
            await server.remove_client(client_to_remove.uid)
            print(f"Клиент '{client_name}' (UID: {client_to_remove.uid}) успешно удален.")
        else:
            print(f"Клиент с именем '{client_name}' не найден.")

    except Exception as e:
        print(f"Ошибка при удалении клиента '{client_name}': {e}")

async def add_client(server: Server, client_name: str) -> None:
    """
    Добавляет клиента с указанным именем.

    :param server: Экземпляр сервера
    :param client_name: Имя нового клиента
    """
    try:
        await server.create_client(client_name)
        print(f"Клиент {client_name} успешно добавлен.")
    except Exception as e:
        print(f"Ошибка при добавлении клиента {client_name}: {e}")

async def get_client_configuration_by_name(server: Server, client_name: str) -> str:
    """
    Получает конфигурационный файл клиента по его имени.

    :param server: Экземпляр сервера
    :param client_name: Имя клиента для получения конфигурации
    :return: Конфигурационный файл в виде текста
    """
    try:
        # Получаем список всех клиентов
        clients = await server.get_clients()

        # Ищем клиента по имени
        client_to_get = None
        for client in clients:
            if client.name == client_name:
                client_to_get = client
                break

        if client_to_get:
            # Получаем конфигурацию клиента
            config = await client_to_get.get_configuration()
            print(f"Конфигурация клиента '{client_name}' успешно получена.")
            return config
        else:
            print(f"Клиент с именем '{client_name}' не найден.")
            return None
    except Exception as e:
        print(f"Ошибка при получении конфигурации клиента '{client_name}': {e}")
        return None

async def save_client_configuration(server: Server, client_name: str) -> str:
    """
    Сохраняет конфигурацию клиента в файл с расширением .conf и именем клиента.

    :param server: Экземпляр сервера
    :param client_name: Имя клиента для получения конфигурации
    :return: Путь к сохраненному файлу
    """
    try:
        # Получаем конфигурацию клиента по имени
        config_text = await get_client_configuration_by_name(server, client_name)

        if config_text is None:
            print(f"Конфигурация для клиента {client_name} не найдена.")
            return None

        # Указываем путь к папке auth
        folder_path = "app/auth"

        # Формируем путь к файлу с расширением .conf
        file_path = os.path.join(folder_path, f"{client_name}.conf")

        # Записываем конфигурацию в файл
        with open(file_path, "w") as config_file:
            config_file.write(config_text)

        print(f"Конфигурация клиента {client_name} успешно сохранена в {file_path}.")
        return file_path

    except Exception as e:
        print(f"Ошибка при сохранении конфигурации для клиента {client_name}: {e}")
        return None

async def get_client_count(server: Server) -> int:
    """
    Возвращает количество клиентов на сервере.

    :param server: Экземпляр сервера
    :return: Количество клиентов
    """

    clients = await server.get_clients()
    client_count = len(clients)
    return client_count




