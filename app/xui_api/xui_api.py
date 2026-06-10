from __future__ import annotations

import logging
from datetime import date, datetime, time
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import aiohttp

import config

logger = logging.getLogger(__name__)

SUPPORTED_LINK_PROTOCOLS = {"vmess", "vless", "trojan", "shadowsocks", "hysteria"}


class XUIAPIError(RuntimeError):
    pass


def _build_base_url(
    address: str | None = None,
    port: int | str | None = None,
    base_path: str | None = None,
) -> str:
    address = str(address if address is not None else getattr(config, "XUI_PANEL_ADDRESS", "") or "").strip().rstrip("/")
    if not address:
        raise XUIAPIError("VLESS panel address is empty")

    if not address.startswith(("http://", "https://")):
        address = f"http://{address}"

    parsed = urlsplit(address)
    port = getattr(config, "XUI_PANEL_PORT", None) if port is None else port
    netloc = parsed.netloc

    if port not in (None, "", 0, "0"):
        host = parsed.hostname or parsed.netloc
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        netloc = f"{host}:{int(port)}"

    configured_base_path = str(
        base_path if base_path is not None else getattr(config, "XUI_PANEL_BASE_PATH", "") or ""
    ).strip("/")
    path_parts = [part.strip("/") for part in (parsed.path, configured_base_path) if part.strip("/")]
    base_path = "/" + "/".join(path_parts) if path_parts else ""

    return urlunsplit((parsed.scheme, netloc, base_path, "", "")).rstrip("/")


def _with_scheme(address: str) -> str:
    if address.startswith(("http://", "https://")):
        return address
    return f"http://{address}"


def _replace_port(address: str, port: int | str | None, *, keep_path: bool = True) -> str:
    address = _with_scheme(str(address or "").strip().rstrip("/"))
    parsed = urlsplit(address)
    netloc = parsed.netloc

    if port not in (None, "", 0, "0"):
        host = parsed.hostname or parsed.netloc
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        netloc = f"{host}:{int(port)}"

    path = parsed.path if keep_path else ""
    return urlunsplit((parsed.scheme, netloc, path.rstrip("/"), "", "")).rstrip("/")


def _subscription_base_url(
    settings: dict[str, Any],
    *,
    configured_address: str | None = None,
    configured_port: int | str | None = None,
    panel_address: str | None = None,
    panel_port: int | str | None = None,
) -> str:
    configured_address = str(
        configured_address if configured_address is not None else getattr(config, "XUI_SUBSCRIPTION_ADDRESS", "") or ""
    ).strip()
    configured_port = getattr(config, "XUI_SUBSCRIPTION_PORT", 0) if configured_port is None else configured_port
    if configured_address:
        return _replace_port(configured_address, configured_port, keep_path=True)

    settings_uri = str(settings.get("subURI") or "").strip()
    if settings_uri:
        return _replace_port(settings_uri, configured_port or None, keep_path=True)

    panel_address = str(
        panel_address if panel_address is not None else getattr(config, "XUI_PANEL_ADDRESS", "") or ""
    ).strip()
    panel_port = getattr(config, "XUI_PANEL_PORT", 0) if panel_port is None else panel_port
    subscription_port = configured_port or settings.get("subPort") or panel_port
    return _replace_port(panel_address, subscription_port, keep_path=False)


def _subscription_path(settings: dict[str, Any], sub_id: str, configured_path: str | None = None) -> str:
    configured_path = str(
        configured_path if configured_path is not None else getattr(config, "XUI_SUBSCRIPTION_PATH", "") or ""
    ).strip()
    path = configured_path or str(settings.get("subPath") or "/sub/").strip()
    path = "/" + path.strip("/")
    return f"{path}/{quote(sub_id, safe='')}"


def _headers(token: str | None = None) -> dict[str, str]:
    token = str(token if token is not None else getattr(config, "XUI_API_TOKEN", "") or "").strip()
    if not token:
        raise XUIAPIError("VLESS API token is empty")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }


def _parse_inbound_ids(raw) -> list[int]:
    if isinstance(raw, str):
        values = [item.strip() for item in raw.split(",")]
    else:
        values = list(raw or [])

    inbound_ids: list[int] = []
    for value in values:
        try:
            inbound_ids.append(int(value))
        except (TypeError, ValueError):
            logger.warning("Invalid VLESS inbound id ignored: %r", value)
    return inbound_ids


def _configured_inbound_ids() -> list[int]:
    return _parse_inbound_ids(getattr(config, "XUI_INBOUND_IDS", []))


def gb_to_bytes(gb_value: int | float | str | None) -> int:
    try:
        gb = float(gb_value or 0)
    except (TypeError, ValueError):
        return 0
    if gb <= 0:
        return 0
    return int(gb * 1024 * 1024 * 1024)


def expiry_to_ms(expiry: date | datetime | str | None) -> int:
    if expiry is None:
        return 0
    if isinstance(expiry, datetime):
        dt = expiry
    elif isinstance(expiry, date):
        dt = datetime.combine(expiry, time.max)
    else:
        text = str(expiry).strip()
        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
            try:
                dt = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        else:
            raise XUIAPIError(f"Invalid expiry date: {expiry!r}")
    return int(dt.timestamp() * 1000)


def ms_to_date(value: int | str | None) -> date | None:
    try:
        timestamp = int(value or 0)
    except (TypeError, ValueError):
        return None
    if timestamp <= 0:
        return None
    return datetime.fromtimestamp(timestamp / 1000).date()


class XUIClient:
    def __init__(
        self,
        base_url: str | None = None,
        *,
        token: str | None = None,
        inbound_ids: list[int] | None = None,
        verify_ssl: bool | None = None,
        total_gb: int | float | str | None = None,
        limit_ip: int | str | None = None,
        reset_days: int | str | None = None,
        subscription_address: str | None = None,
        subscription_port: int | str | None = None,
        subscription_path: str | None = None,
        panel_address: str | None = None,
        panel_port: int | str | None = None,
    ):
        self.base_url = (base_url or _build_base_url()).rstrip("/")
        self.timeout = aiohttp.ClientTimeout(total=30)
        self.token = token
        self.inbound_ids = inbound_ids
        self.verify_ssl = bool(getattr(config, "XUI_VERIFY_SSL", False) if verify_ssl is None else verify_ssl)
        self.total_gb = getattr(config, "XUI_CLIENT_TOTAL_GB", 0) if total_gb is None else total_gb
        self.limit_ip = getattr(config, "XUI_CLIENT_LIMIT_IP", 0) if limit_ip is None else limit_ip
        self.reset_days = getattr(config, "XUI_CLIENT_RESET_DAYS", 0) if reset_days is None else reset_days
        self.subscription_address = subscription_address
        self.subscription_port = subscription_port
        self.subscription_path = subscription_path
        self.panel_address = panel_address
        self.panel_port = panel_port

    @classmethod
    def from_server(cls, server) -> "XUIClient":
        inbound_ids = _parse_inbound_ids(getattr(server, "inbound_ids", "") or "")
        return cls(
            base_url=_build_base_url(
                getattr(server, "host_ip", "") or "",
                getattr(server, "port", "") or "",
                getattr(server, "panel_base_path", "") or "",
            ),
            token=getattr(server, "password", "") or "",
            inbound_ids=inbound_ids or None,
            subscription_address=getattr(server, "subscription_address", "") or "",
            subscription_port=getattr(server, "subscription_port", "") or "",
            subscription_path=getattr(server, "subscription_path", "") or "",
            panel_address=getattr(server, "host_ip", "") or "",
            panel_port=getattr(server, "port", "") or "",
        )

    async def _request(self, method: str, path: str, **kwargs) -> Any:
        url = f"{self.base_url}{path}"
        connector = aiohttp.TCPConnector(ssl=self.verify_ssl)
        async with aiohttp.ClientSession(timeout=self.timeout, connector=connector, headers=_headers(self.token)) as session:
            async with session.request(method, url, **kwargs) as response:
                response_text = await response.text()
                try:
                    data = await response.json(content_type=None)
                except Exception as exc:
                    raise XUIAPIError(
                        f"VLESS panel returned non-JSON response: status={response.status} body={response_text[:200]}"
                    ) from exc

        if response.status >= 400:
            raise XUIAPIError(f"VLESS panel HTTP error: status={response.status} body={response_text[:200]}")

        if isinstance(data, dict) and data.get("success") is False:
            raise XUIAPIError(str(data.get("msg") or "VLESS API request failed"))

        return data

    async def get_inbound_options(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/panel/api/inbounds/options")
        return list((data or {}).get("obj") or [])

    async def get_target_inbound_ids(self) -> list[int]:
        configured = self.inbound_ids if self.inbound_ids is not None else _configured_inbound_ids()
        if configured:
            return configured

        options = await self.get_inbound_options()
        return [
            int(item["id"])
            for item in options
            if item.get("id") is not None and item.get("protocol") in SUPPORTED_LINK_PROTOCOLS
        ]

    async def get_all_settings(self) -> dict[str, Any]:
        data = await self._request("POST", "/panel/api/setting/all")
        obj = (data or {}).get("obj")
        return dict(obj) if isinstance(obj, dict) else {}

    async def add_client(
        self,
        *,
        email: str,
        expiry: date | datetime | str,
        tg_id: int,
        sub_id: str,
        comment: str = "",
    ) -> dict[str, Any]:
        inbound_ids = await self.get_target_inbound_ids()
        if not inbound_ids:
            raise XUIAPIError("No VLESS inbound IDs configured or available")

        client = {
            "email": email,
            "totalGB": gb_to_bytes(self.total_gb),
            "expiryTime": expiry_to_ms(expiry),
            "tgId": int(tg_id),
            "limitIp": int(self.limit_ip or 0),
            "enable": True,
            "reset": int(self.reset_days or 0),
            "security": "auto",
            "subId": sub_id,
            "comment": comment,
        }
        data = await self._request(
            "POST",
            "/panel/api/clients/add",
            json={"client": client, "inboundIds": inbound_ids},
        )
        return dict(data or {})

    async def get_client(self, email: str) -> dict[str, Any] | None:
        data = await self._request("GET", f"/panel/api/clients/get/{quote(email, safe='')}")
        obj = (data or {}).get("obj")
        return dict(obj) if isinstance(obj, dict) else None

    async def update_client(self, email: str, payload: dict[str, Any]) -> dict[str, Any]:
        data = await self._request(
            "POST",
            f"/panel/api/clients/update/{quote(email, safe='')}",
            json=payload,
        )
        return dict(data or {})

    async def update_client_expiry(self, email: str, expiry: date | datetime | str) -> dict[str, Any]:
        client = await self.get_client(email)
        if not client:
            raise XUIAPIError(f"VLESS client not found: {email}")

        client["expiryTime"] = expiry_to_ms(expiry)
        client["enable"] = True

        for key, default in {
            "comment": "",
            "limitIp": 0,
            "reset": 0,
            "security": "auto",
            "totalGB": 0,
            "tgId": 0,
        }.items():
            client.setdefault(key, default)

        return await self.update_client(email, client)

    async def delete_client(self, email: str) -> dict[str, Any]:
        data = await self._request("POST", f"/panel/api/clients/del/{quote(email, safe='')}")
        return dict(data or {})

    async def get_client_links(self, email: str) -> list[str]:
        data = await self._request("GET", f"/panel/api/clients/links/{quote(email, safe='')}")
        return list((data or {}).get("obj") or [])

    async def get_subscription_links(self, sub_id: str) -> list[str]:
        data = await self._request("GET", f"/panel/api/clients/subLinks/{quote(sub_id, safe='')}")
        return list((data or {}).get("obj") or [])

    async def get_subscription_url(self, sub_id: str) -> str:
        settings = await self.get_all_settings()
        base_url = _subscription_base_url(
            settings,
            configured_address=self.subscription_address,
            configured_port=self.subscription_port,
            panel_address=self.panel_address,
            panel_port=self.panel_port,
        )
        return f"{base_url}{_subscription_path(settings, sub_id, self.subscription_path)}"

    async def get_client_traffic(self, email: str) -> dict[str, Any] | None:
        data = await self._request("GET", f"/panel/api/clients/traffic/{quote(email, safe='')}")
        obj = (data or {}).get("obj")
        return dict(obj) if isinstance(obj, dict) else None

    async def count_clients(self) -> int:
        data = await self._request("GET", "/panel/api/clients/list")
        return len(list((data or {}).get("obj") or []))


def _client(server=None) -> XUIClient:
    return XUIClient.from_server(server) if server is not None else XUIClient()


async def add_client_xui(
    *,
    email: str,
    expiry: date | datetime | str,
    tg_id: int,
    sub_id: str,
    comment: str = "",
    server=None,
) -> dict[str, Any]:
    return await _client(server).add_client(
        email=email,
        expiry=expiry,
        tg_id=tg_id,
        sub_id=sub_id,
        comment=comment,
    )


async def update_client_expiry_xui(email: str, expiry: date | datetime | str, server=None) -> dict[str, Any]:
    return await _client(server).update_client_expiry(email, expiry)


async def remove_client_xui(email: str, server=None) -> dict[str, Any]:
    return await _client(server).delete_client(email)


async def get_client_xui(email: str, server=None) -> dict[str, Any] | None:
    return await _client(server).get_client(email)


async def get_client_links_xui(email: str, server=None) -> list[str]:
    return await _client(server).get_client_links(email)


async def get_subscription_links_xui(sub_id: str, server=None) -> list[str]:
    return await _client(server).get_subscription_links(sub_id)


async def get_subscription_url_xui(sub_id: str, server=None) -> str:
    return await _client(server).get_subscription_url(sub_id)


async def get_client_traffic_xui(email: str, server=None) -> dict[str, Any] | None:
    return await _client(server).get_client_traffic(email)


async def get_client_count_xui(server=None) -> int:
    return await _client(server).count_clients()
