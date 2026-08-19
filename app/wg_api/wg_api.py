from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

import aiohttp

from app.paths import CONFIG_DIR, config_file_path
from app.settings import wg_max_clients, wg_request_timeout_seconds, wg_verify_ssl


logger = logging.getLogger(__name__)

_CLIENT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_T = TypeVar("_T")
_provision_locks: dict[str, asyncio.Lock] = {}


class WireGuardError(RuntimeError):
    """Base error raised by the WireGuard integration."""


class WireGuardClientNotFound(WireGuardError):
    pass


class WireGuardCapacityError(WireGuardError):
    pass


@dataclass(slots=True)
class WireGuardClient:
    uid: str
    name: str
    server: "WireGuardServer"

    async def get_configuration(self) -> str:
        return await self.server.request_text(
            "GET",
            f"/api/wireguard/client/{self.uid}/configuration",
        )


class WireGuardServer:
    def __init__(
        self,
        url: str,
        password: str,
        session: aiohttp.ClientSession,
    ) -> None:
        self.url = url.rstrip("/")
        self._password = password
        self._session = session

    def _url(self, path: str) -> str:
        return f"{self.url}{path}"

    async def _request(self, method: str, path: str, **kwargs) -> aiohttp.ClientResponse:
        response = await self._session.request(method, self._url(path), **kwargs)
        try:
            response.raise_for_status()
        except Exception:
            response.release()
            raise
        return response

    async def request_json(self, method: str, path: str, **kwargs):
        response = await self._request(method, path, **kwargs)
        try:
            return await response.json(content_type=None)
        finally:
            response.release()

    async def request_text(self, method: str, path: str, **kwargs) -> str:
        response = await self._request(method, path, **kwargs)
        try:
            return await response.text()
        finally:
            response.release()

    async def request_no_content(self, method: str, path: str, **kwargs) -> None:
        response = await self._request(method, path, **kwargs)
        try:
            await response.read()
        finally:
            response.release()

    async def login(self) -> None:
        try:
            session_data = await self.request_json("GET", "/api/session")
        except aiohttp.ClientResponseError as exc:
            if exc.status not in {401, 403}:
                raise
            session_data = {}

        if bool(session_data.get("authenticated")):
            return

        await self.request_no_content(
            "POST",
            "/api/session",
            json={"password": self._password},
        )
        session_data = await self.request_json("GET", "/api/session")
        if not bool(session_data.get("authenticated")):
            raise WireGuardError("WireGuard API authentication failed")

    async def get_clients(self) -> list[WireGuardClient]:
        data = await self.request_json("GET", "/api/wireguard/client")
        if not isinstance(data, list):
            raise WireGuardError("WireGuard API returned an invalid client list")
        clients: list[WireGuardClient] = []
        for item in data:
            if not isinstance(item, dict) or "id" not in item or "name" not in item:
                raise WireGuardError("WireGuard API returned an invalid client record")
            clients.append(
                WireGuardClient(uid=str(item["id"]), name=str(item["name"]), server=self)
            )
        return clients

    async def create_client(self, name: str) -> None:
        await self.request_no_content(
            "POST",
            "/api/wireguard/client",
            json={"name": name},
        )

    async def remove_client(self, uid: str) -> None:
        await self.request_no_content(
            "DELETE",
            f"/api/wireguard/client/{uid}",
        )


def validate_client_name(client_name: str) -> str:
    normalized = (client_name or "").strip()
    if not _CLIENT_NAME_RE.fullmatch(normalized):
        raise ValueError(
            "WireGuard client name must contain 1-64 letters, digits, '.', '_' or '-'"
        )
    return normalized


def _create_wg_session() -> aiohttp.ClientSession:
    connector = aiohttp.TCPConnector(ssl=wg_verify_ssl())
    timeout = aiohttp.ClientTimeout(total=wg_request_timeout_seconds())
    cookie_jar = aiohttp.CookieJar(unsafe=True)
    return aiohttp.ClientSession(
        connector=connector,
        timeout=timeout,
        cookie_jar=cookie_jar,
    )


async def _with_server(
    url: str,
    password: str,
    action: Callable[[WireGuardServer], Awaitable[_T]],
) -> _T:
    if not str(url).startswith(("https://", "http://")):
        raise ValueError("WireGuard API URL must start with http:// or https://")
    if not password:
        raise ValueError("WireGuard API password is empty")

    async with _create_wg_session() as session:
        server = WireGuardServer(url.rstrip("/"), password, session)
        await authorize(server)
        return await action(server)


async def add_client_wg(client_name: str, url: str, password: str) -> None:
    normalized = validate_client_name(client_name)

    async def action(server: WireGuardServer) -> None:
        await add_client(server, normalized)

    await _with_server(url, password, action)


async def get_config_wg(client_name: str, url: str, password: str) -> str:
    normalized = validate_client_name(client_name)

    async def action(server: WireGuardServer) -> str:
        return await save_client_configuration(server, normalized)

    return await _with_server(url, password, action)


async def provision_client_wg(client_name: str, url: str, password: str) -> str:
    """Create a client if needed and persist a verified non-empty configuration."""
    normalized = validate_client_name(client_name)

    async def action(server: WireGuardServer) -> str:
        clients = await server.get_clients()
        existing = next((client for client in clients if client.name == normalized), None)
        created = existing is None

        try:
            if created:
                if len(clients) >= wg_max_clients():
                    raise WireGuardCapacityError(
                        f"WireGuard server has reached the client limit: {len(clients)}"
                    )
                await server.create_client(normalized)
            return await save_client_configuration(server, normalized)
        except Exception:
            if created:
                try:
                    await remove_client_by_name(server, normalized)
                except Exception:
                    logger.exception(
                        "Failed to compensate WireGuard client creation: client=%s url=%s",
                        normalized,
                        url,
                    )
            raise

    lock = _provision_locks.setdefault(url.rstrip("/"), asyncio.Lock())
    async with lock:
        return await _with_server(url, password, action)


async def remove_client_wg(client_name: str, url: str, password: str) -> bool:
    normalized = validate_client_name(client_name)

    async def action(server: WireGuardServer) -> bool:
        return await remove_client_by_name(server, normalized)

    return await _with_server(url, password, action)


async def get_client_count_wg(url: str, password: str) -> int:
    return await _with_server(url, password, get_client_count)


async def authorize(server: WireGuardServer) -> None:
    await server.login()


async def remove_client_by_name(server: WireGuardServer, client_name: str) -> bool:
    clients = await server.get_clients()
    client = next((item for item in clients if item.name == client_name), None)
    if client is None:
        return False
    await server.remove_client(client.uid)
    return True


async def add_client(server: WireGuardServer, client_name: str) -> None:
    await server.create_client(client_name)


async def get_client_configuration_by_name(server: WireGuardServer, client_name: str) -> str:
    clients = await server.get_clients()
    client = next((item for item in clients if item.name == client_name), None)
    if client is None:
        raise WireGuardClientNotFound(f"WireGuard client not found: {client_name}")

    configuration = await client.get_configuration()
    if not configuration or not str(configuration).strip():
        raise WireGuardError(f"WireGuard returned an empty configuration: {client_name}")
    return str(configuration)


def _save_configuration_text(client_name: str, config_text: str) -> Path:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    file_path = config_file_path(client_name)
    temporary_path = file_path.with_suffix(".conf.tmp")
    temporary_path.write_text(config_text, encoding="utf-8", newline="\n")
    temporary_path.replace(file_path)
    try:
        file_path.chmod(0o600)
    except OSError:
        logger.warning("Could not restrict permissions for WireGuard config: %s", file_path)
    return file_path


async def save_client_configuration(server: WireGuardServer, client_name: str) -> str:
    normalized = validate_client_name(client_name)
    config_text = await get_client_configuration_by_name(server, normalized)
    return str(_save_configuration_text(normalized, config_text))


async def get_client_count(server: WireGuardServer) -> int:
    clients = await server.get_clients()
    return len(clients)
