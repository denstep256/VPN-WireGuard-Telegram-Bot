from __future__ import annotations

import secrets
from contextlib import asynccontextmanager
from datetime import date, datetime, time
from urllib.parse import quote, urlsplit, urlunsplit
from uuid import uuid4
from zoneinfo import ZoneInfo

import aiohttp

import config


class XUIAPIError(RuntimeError):
    pass


VISION_FLOW = "xtls-rprx-vision"
# Inbound 5 in the panel uses protocol hysteria (Hysteria2).
INBOUND_TYPES = {
    "reality": ("vless", {"tcp", "raw"}, "reality"),
    "xhttp": ("vless", {"xhttp", "splithttp"}, None),
    "hysteria2": ("hysteria", None, None),
    "xtls": ("vless", {"tcp", "raw"}, "tls"),
}


def expiry_to_ms(expiry: date | datetime | str) -> int:
    if isinstance(expiry, str):
        expiry = date.fromisoformat(expiry) if len(expiry) == 10 else datetime.fromisoformat(expiry)
    if not isinstance(expiry, datetime):
        expiry = datetime.combine(expiry, time.max)
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=ZoneInfo(config.VPN_TIMEZONE))
    return int(expiry.timestamp() * 1000)


def generate_sub_id() -> str:
    return secrets.token_hex(8)


class XUIClient:
    def __init__(self, session: aiohttp.ClientSession, base_url: str):
        self.session = session
        self.base_url = base_url

    @classmethod
    @asynccontextmanager
    async def connect(cls):
        address = config.XUI_PANEL_ADDRESS.strip().rstrip("/")
        parsed = urlsplit(address)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.query or parsed.fragment:
            raise XUIAPIError("Укажите полный HTTPS-адрес панели в XUI_PANEL_ADDRESS.")

        headers = {"Accept": "application/json"}
        token = config.XUI_API_TOKEN.strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"

        async with aiohttp.ClientSession(
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=15),
            connector=aiohttp.TCPConnector(ssl=config.XUI_VERIFY_SSL),
        ) as session:
            client = cls(session, address)
            if not token:
                await client.login()
            yield client

    async def request(self, method: str, path: str, *, missing_ok: bool = False, **kwargs):
        try:
            async with self.session.request(
                method, f"{self.base_url}{path}", allow_redirects=False, **kwargs
            ) as response:
                if missing_ok and response.status == 404:
                    # An unknown route returns HTML. That is an API mismatch, not an absent client.
                    try:
                        data = await response.json(content_type=None)
                    except ValueError:
                        data = None
                    if isinstance(data, dict) and data.get("success") is False:
                        return None
                if response.status < 200 or response.status >= 300:
                    raise XUIAPIError(f"3x-ui {method} {path}: HTTP {response.status}")
                try:
                    data = await response.json(content_type=None)
                except ValueError:
                    raise XUIAPIError(f"3x-ui {method} {path}: ожидался JSON") from None
        except (aiohttp.ClientError, TimeoutError):
            raise XUIAPIError(f"3x-ui {method} {path}: ошибка подключения") from None

        if isinstance(data, dict) and data.get("success") is True:
            return data.get("obj")
        if missing_ok and isinstance(data, dict) and "record not found" in str(data.get("msg", "")).lower():
            return None
        # The server's error text can contain credentials or a subscription URL.
        raise XUIAPIError(f"3x-ui отклонила запрос {method} {path}")

    async def login(self) -> None:
        if not config.XUI_PANEL_USERNAME or not config.XUI_PANEL_PASSWORD:
            raise XUIAPIError("Заполните XUI_PANEL_USERNAME и XUI_PANEL_PASSWORD либо XUI_API_TOKEN.")
        await self.refresh_csrf()
        await self.request("POST", "/login", json={
            "username": config.XUI_PANEL_USERNAME,
            "password": config.XUI_PANEL_PASSWORD,
        })
        await self.refresh_csrf()

    async def refresh_csrf(self) -> None:
        token = await self.request("GET", "/csrf-token")
        if not isinstance(token, str) or not token:
            raise XUIAPIError("3x-ui не вернула CSRF-токен.")
        self.session.headers["X-CSRF-Token"] = token

    async def get_target_inbound_ids(self) -> list[int]:
        configured = config.XUI_INBOUND_IDS
        if set(configured) != set(INBOUND_TYPES) or len(set(configured.values())) != len(INBOUND_TYPES):
            raise XUIAPIError("Задайте четыре разных ID в XUI_INBOUND_IDS.")
        options = await self.request("GET", "/panel/api/inbounds/options")
        by_id = {item["id"]: item for item in options}
        for name, (protocol, networks, security) in INBOUND_TYPES.items():
            inbound_id = configured[name]
            item = by_id.get(inbound_id, {})
            if (
                not item.get("enable")
                or item.get("protocol") != protocol
                or (networks and item.get("network") not in networks)
                or (security and item.get("security") != security)
                or (name in {"reality", "xtls"} and not item.get("tlsFlowCapable"))
            ):
                raise XUIAPIError(f"Inbound {inbound_id} не соответствует активному профилю {name}.")
        return list(configured.values())

    async def get_client(self, email: str) -> dict | None:
        path = f"/panel/api/clients/get/{quote(email, safe='')}"
        result = await self.request("GET", path, missing_ok=True)
        if result is not None and (not isinstance(result, dict) or not isinstance(result.get("client"), dict)):
            raise XUIAPIError("3x-ui вернула неожиданный формат клиента.")
        return result

    async def ensure_client(
        self, *, email: str, expiry: date | datetime | str, tg_id: int, username: str | None = None,
        sub_id: str | None = None, inbound_ids: list[int] | None = None,
    ) -> str:
        if inbound_ids is None:
            inbound_ids = await self.get_target_inbound_ids()
        record = await self.get_client(email)
        remote = record["client"] if record else {}
        remote_sub_id = remote.get("subId")
        if record and int(remote.get("tgId") or 0) != tg_id and not (sub_id and sub_id == remote_sub_id):
            raise XUIAPIError(f"Клиент {email} в 3x-ui принадлежит другой записи.")
        sub_id = remote_sub_id or sub_id or generate_sub_id()
        expiry_ms = expiry_to_ms(expiry)
        quota_bytes = config.XUI_CLIENT_TOTAL_GB * 1024**3
        payload = {
            "totalGB": quota_bytes,
            "limitIp": config.XUI_CLIENT_LIMIT_IP,
            "expiryTime": expiry_ms,
            "tgId": tg_id,
            "subId": sub_id,
            "flow": VISION_FLOW,
            "trafficReset": "monthly",
            "trafficResetDay": config.XUI_TRAFFIC_RESET_DAY,
            "reset": 0,
            "resetDay": 0,
            "resetWeekday": 0,
        }
        changed = record is None
        if record is None:
            payload.update(
                email=email, id=str(uuid4()), auth=secrets.token_urlsafe(24), enable=True,
                comment=f"tg:{tg_id}" + (f" @{username}" if username else ""),
            )
            await self.request(
                "POST", "/panel/api/clients/add", json={"client": payload, "inboundIds": inbound_ids}
            )
        else:
            now_ms = int(datetime.now().timestamp() * 1000)
            if (
                not remote.get("enable")
                and 0 < int(remote.get("expiryTime") or 0) <= now_ms < expiry_ms
                and int(record.get("usedTraffic") or 0) < quota_bytes
            ):
                payload["enable"] = True
            key = quote(email, safe="")
            missing_ids = [inbound_id for inbound_id in inbound_ids if inbound_id not in record["inboundIds"]]
            if missing_ids:
                await self.request("POST", f"/panel/api/clients/{key}/attach", json={"inboundIds": missing_ids})
            changed = bool(missing_ids) or any(remote.get(field) != value for field, value in payload.items())
            if changed:
                await self.request("POST", f"/panel/api/clients/update/{key}", json=payload)
        confirmed = await self.get_client(email) if changed else record
        if not confirmed or not set(inbound_ids).issubset(confirmed["inboundIds"]):
            raise XUIAPIError("3x-ui не подтвердила четыре подключения клиента.")
        expected = ("subId", "totalGB", "limitIp", "expiryTime", "trafficReset", "trafficResetDay", "flow")
        if any(confirmed["client"].get(field) != payload[field] for field in expected):
            raise XUIAPIError("3x-ui не подтвердила срок, квоту, IP-лимит, месячный сброс или XTLS Vision.")
        return sub_id

    async def update_expiry(self, email: str, expiry: date | datetime | str) -> None:
        await self.request(
            "POST", f"/panel/api/clients/update/{quote(email, safe='')}",
            json={"expiryTime": expiry_to_ms(expiry), "reset": 0, "resetDay": 0, "resetWeekday": 0},
        )

    async def delete_client(self, email: str) -> None:
        await self.request("POST", f"/panel/api/clients/del/{quote(email, safe='')}", missing_ok=True)

    async def get_client_traffic(self, email: str) -> dict | None:
        return await self.request("GET", f"/panel/api/clients/traffic/{quote(email, safe='')}", missing_ok=True)

    async def count_clients(self) -> int:
        result = await self.request("GET", "/panel/api/clients/list/paged", params={"page": 1, "pageSize": 1})
        return int(result["total"])

    async def subscription_base_url(self) -> str:
        override = config.XUI_SUBSCRIPTION_URL.strip().rstrip("/")
        if override:
            return override
        settings = await self.request("POST", "/panel/api/setting/all")
        if not isinstance(settings, dict):
            raise XUIAPIError("3x-ui не вернула настройки сервера подписок.")
        if settings.get("subEnable") is False:
            raise XUIAPIError("Сервер подписок 3x-ui отключён.")
        path = "/" + str(settings.get("subPath") or "/sub/").strip("/")
        if settings.get("subURI"):
            public = str(settings["subURI"]).rstrip("/")
            if urlsplit(public).path or path == "/":
                return public
            return f"{public}{path}".rstrip("/")
        panel_url = urlsplit(self.base_url)
        domain = settings.get("subDomain") or panel_url.hostname
        if ":" in domain and not domain.startswith("["):
            domain = f"[{domain}]"
        scheme = "https" if settings.get("subCertFile") and settings.get("subKeyFile") else "http"
        port = int(settings.get("subPort") or 2096)
        return urlunsplit((scheme, f"{domain}:{port}", path, "", "")).rstrip("/")

    async def get_subscription_url(self, sub_id: str) -> str:
        return f"{await self.subscription_base_url()}/{quote(sub_id, safe='')}"
