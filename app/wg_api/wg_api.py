import aiohttp
import os
from wg_easy_api_wrapper.server import Server

# --- NEW: общий хелпер с отключенным SSL ---
def _create_wg_session() -> aiohttp.ClientSession:
    connector = aiohttp.TCPConnector(ssl=False)  # ✅ фикс self-signed cert
    return aiohttp.ClientSession(connector=connector)


async def _with_server(url: str, password: str, fn):
    """
    Единая обертка:
    - создаёт session (ssl=False)
    - создаёт Server
    - логинится
    - выполняет fn(server)
    - закрывает session
    """
    async with _create_wg_session() as session:
        server = Server(url, password, session)
        await authorize(server)
        return await fn(server)


async def add_client_wg(client_name: str, url: str, password: str):
    async def action(server: Server):
        await add_client(server, client_name)
        return None

    return await _with_server(url, password, action)


async def get_config_wg(client_name: str, url: str, password: str):
    async def action(server: Server):
        file_path = await save_client_configuration(server, client_name)
        if file_path:
            print(file_path)
        return file_path

    return await _with_server(url, password, action)


async def remove_client_wg(client_name: str, url: str, password: str):
    async def action(server: Server):
        await remove_client_by_name(server, client_name)
        return None

    return await _with_server(url, password, action)


async def get_client_count_wg(url: str, password: str) -> int:
    async def action(server: Server):
        return await get_client_count(server)

    return await _with_server(url, password, action)


async def authorize(server: Server) -> None:
    await server.login()


async def remove_client_by_name(server: Server, client_name: str) -> None:
    clients = await server.get_clients()

    client_to_remove = None
    for client in clients:
        if client.name == client_name:
            client_to_remove = client
            break

    if client_to_remove:
        await server.remove_client(client_to_remove.uid)


async def add_client(server: Server, client_name: str) -> None:
    await server.create_client(client_name)


async def get_client_configuration_by_name(server: Server, client_name: str) -> str | None:
    try:
        clients = await server.get_clients()

        client_to_get = None
        for client in clients:
            if client.name == client_name:
                client_to_get = client
                break

        if client_to_get:
            return await client_to_get.get_configuration()
        return None
    except Exception:
        return None


async def save_client_configuration(server: Server, client_name: str) -> str | None:
    try:
        config_text = await get_client_configuration_by_name(server, client_name)
        if config_text is None:
            return None

        folder_path = "app/auth"
        file_path = os.path.join(folder_path, f"{client_name}.conf")

        with open(file_path, "w") as config_file:
            config_file.write(config_text)

        return file_path
    except Exception:
        return None


async def get_client_count(server: Server) -> int:
    clients = await server.get_clients()
    return len(clients)