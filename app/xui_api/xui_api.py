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


def _build_base_url() -> str:
    address = str(getattr(config, "XUI_PANEL_ADDRESS", "") or "").strip().rstrip("/")
    if not address:
        raise XUIAPIError("XUI_PANEL_ADDRESS is empty")

    if not address.startswith(("http://", "https://")):
        address = f"http://{address}"

    parsed = urlsplit(address)
    port = getattr(config, "XUI_PANEL_PORT", None)
    netloc = parsed.netloc

    if port not in (None, "", 0, "0"):
        host = parsed.hostname or parsed.netloc
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        netloc = f"{host}:{int(port)}"

    configured_base_path = str(getattr(config, "XUI_PANEL_BASE_PATH", "") or "").strip("/")
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


def _subscription_base_url(settings: dict[str, Any]) -> str:
    configured_address = str(getattr(config, "XUI_SUBSCRIPTION_ADDRESS", "") or "").strip()
    configured_port = getattr(config, "XUI_SUBSCRIPTION_PORT", 0)
    if configured_address:
        return _replace_port(configured_address, configured_port, keep_path=True)

    settings_uri = str(settings.get("subURI") or "").strip()
    if settings_uri:
        return _replace_port(settings_uri, configured_port or None, keep_path=True)

    panel_address = str(getattr(config, "XUI_PANEL_ADDRESS", "") or "").strip()
    subscription_port = configured_port or settings.get("subPort") or getattr(config, "XUI_PANEL_PORT", 0)
    return _replace_port(panel_address, subscription_port, keep_path=False)


def _subscription_path(settings: dict[str, Any], sub_id: str) -> str:
    configured_path = str(getattr(config, "XUI_SUBSCRIPTION_PATH", "") or "").strip()
    path = configured_path or str(settings.get("subPath") or "/sub/").strip()
    path = "/" + path.strip("/")
    return f"{path}/{quote(sub_id, safe='')}"


def _headers() -> dict[str, str]:
    token = str(getattr(config, "XUI_API_TOKEN", "") or "").strip()
    if not token:
        raise XUIAPIError("XUI_API_TOKEN is empty")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }


def _configured_inbound_ids() -> list[int]:
    raw = getattr(config, "XUI_INBOUND_IDS", [])
    if isinstance(raw, str):
        values = [item.strip() for item in raw.split(",")]
    else:
        values = list(raw or [])

    inbound_ids: list[int] = []
    for value in values:
        try:
            inbound_ids.append(int(value))
        except (TypeError, ValueError):
            logger.warning("Invalid XUI inbound id ignored: %r", value)
    return inbound_ids


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
    def __init__(self, base_url: str | None = None):
        self.base_url = (base_url or _build_base_url()).rstrip("/")
        self.timeout = aiohttp.ClientTimeout(total=30)

    async def _request(self, method: str, path: str, **kwargs) -> Any:
        url = f"{self.base_url}{path}"
        connector = aiohttp.TCPConnector(ssl=bool(getattr(config, "XUI_VERIFY_SSL", False)))
        async with aiohttp.ClientSession(timeout=self.timeout, connector=connector, headers=_headers()) as session:
            async with session.request(method, url, **kwargs) as response:
                response_text = await response.text()
                try:
                    data = await response.json(content_type=None)
                except Exception as exc:
                    raise XUIAPIError(
                        f"3xUI returned non-JSON response: status={response.status} body={response_text[:200]}"
                    ) from exc

        if response.status >= 400:
            raise XUIAPIError(f"3xUI HTTP error: status={response.status} body={response_text[:200]}")

        if isinstance(data, dict) and data.get("success") is False:
            raise XUIAPIError(str(data.get("msg") or "3xUI API request failed"))

        return data

    async def get_inbound_options(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/panel/api/inbounds/options")
        return list((data or {}).get("obj") or [])

    async def get_target_inbound_ids(self) -> list[int]:
        configured = _configured_inbound_ids()
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
            raise XUIAPIError("No 3xUI inbound IDs configured or available")

        client = {
            "email": email,
            "totalGB": gb_to_bytes(getattr(config, "XUI_CLIENT_TOTAL_GB", 0)),
            "expiryTime": expiry_to_ms(expiry),
            "tgId": int(tg_id),
            "limitIp": int(getattr(config, "XUI_CLIENT_LIMIT_IP", 0) or 0),
            "enable": True,
            "reset": int(getattr(config, "XUI_CLIENT_RESET_DAYS", 0) or 0),
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
            raise XUIAPIError(f"3xUI client not found: {email}")

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
        return f"{_subscription_base_url(settings)}{_subscription_path(settings, sub_id)}"

    async def get_client_traffic(self, email: str) -> dict[str, Any] | None:
        data = await self._request("GET", f"/panel/api/clients/traffic/{quote(email, safe='')}")
        obj = (data or {}).get("obj")
        return dict(obj) if isinstance(obj, dict) else None

    async def count_clients(self) -> int:
        data = await self._request("GET", "/panel/api/clients/list")
        return len(list((data or {}).get("obj") or []))


async def add_client_xui(
    *,
    email: str,
    expiry: date | datetime | str,
    tg_id: int,
    sub_id: str,
    comment: str = "",
) -> dict[str, Any]:
    return await XUIClient().add_client(
        email=email,
        expiry=expiry,
        tg_id=tg_id,
        sub_id=sub_id,
        comment=comment,
    )


async def update_client_expiry_xui(email: str, expiry: date | datetime | str) -> dict[str, Any]:
    return await XUIClient().update_client_expiry(email, expiry)


async def remove_client_xui(email: str) -> dict[str, Any]:
    return await XUIClient().delete_client(email)


async def get_client_xui(email: str) -> dict[str, Any] | None:
    return await XUIClient().get_client(email)


async def get_client_links_xui(email: str) -> list[str]:
    return await XUIClient().get_client_links(email)


async def get_subscription_links_xui(sub_id: str) -> list[str]:
    return await XUIClient().get_subscription_links(sub_id)


async def get_subscription_url_xui(sub_id: str) -> str:
    return await XUIClient().get_subscription_url(sub_id)


async def get_client_traffic_xui(email: str) -> dict[str, Any] | None:
    return await XUIClient().get_client_traffic(email)


async def get_client_count_xui() -> int:
    return await XUIClient().count_clients()
