from pathlib import Path
from tempfile import NamedTemporaryFile

import aiohttp
from wg_easy_api_wrapper.server import Server

import config


async def _with_server(url: str, password: str, action):
    connector = aiohttp.TCPConnector(ssl=config.WG_VERIFY_SSL)
    async with aiohttp.ClientSession(
        connector=connector, timeout=aiohttp.ClientTimeout(total=15), raise_for_status=True,
    ) as session:
        server = Server(url, password, session)
        await server.login()
        return await action(server)


async def ensure_client_wg(client_name: str, url: str, password: str, path: Path) -> None:
    async def action(server: Server):
        client = next((item for item in await server.get_clients() if item.name == client_name), None)
        if client is None:
            await server.create_client(client_name)
            client = next((item for item in await server.get_clients() if item.name == client_name), None)
            if client is None:
                raise RuntimeError("wg-easy не вернул созданного клиента")
        configuration = await client.get_configuration()
        if not configuration:
            raise RuntimeError("wg-easy не вернул конфигурацию")
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=path.parent, mode="w", encoding="utf-8", delete=False) as temporary:
            temporary.write(configuration)
        temporary_path = Path(temporary.name)
        try:
            temporary_path.replace(path)
        finally:
            temporary_path.unlink(missing_ok=True)

    await _with_server(url, password, action)


async def remove_client_wg(client_name: str, url: str, password: str) -> None:
    async def action(server: Server):
        client = next((item for item in await server.get_clients() if item.name == client_name), None)
        if client is not None:
            await server.remove_client(client.uid)

    await _with_server(url, password, action)


async def get_client_count_wg(url: str, password: str) -> int:
    async def action(server: Server):
        return len(await server.get_clients())

    return await _with_server(url, password, action)
