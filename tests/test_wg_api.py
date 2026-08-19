import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

from app.wg_api import wg_api


class WireGuardApiTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _response(*, json_data=None, text_data="", body=b""):
        return SimpleNamespace(
            raise_for_status=MagicMock(),
            json=AsyncMock(return_value=json_data),
            text=AsyncMock(return_value=text_data),
            read=AsyncMock(return_value=body),
            release=MagicMock(),
        )

    async def test_session_disables_tls_certificate_verification(self):
        session = wg_api._create_wg_session()
        try:
            self.assertIs(session.connector._ssl, False)
        finally:
            await session.close()

    async def test_server_login_uses_v14_session_contract(self):
        session = SimpleNamespace(
            request=AsyncMock(
                side_effect=[
                    self._response(json_data={"authenticated": False}),
                    self._response(),
                    self._response(json_data={"authenticated": True}),
                ]
            )
        )
        server = wg_api.WireGuardServer("https://wg.example", "secret", session)

        await server.login()

        self.assertEqual(
            session.request.await_args_list,
            [
                call("GET", "https://wg.example/api/session"),
                call(
                    "POST",
                    "https://wg.example/api/session",
                    json={"password": "secret"},
                ),
                call("GET", "https://wg.example/api/session"),
            ],
        )

    async def test_server_client_crud_contract(self):
        session = SimpleNamespace(
            request=AsyncMock(
                side_effect=[
                    self._response(json_data=[{"id": "42", "name": "ZENITH-12345678"}]),
                    self._response(),
                    self._response(text_data="[Interface]\nPrivateKey = test\n"),
                    self._response(),
                ]
            )
        )
        server = wg_api.WireGuardServer("https://wg.example/", "secret", session)

        clients = await server.get_clients()
        await server.create_client("ZENITH-87654321")
        configuration = await clients[0].get_configuration()
        await server.remove_client("42")

        self.assertEqual(clients[0].uid, "42")
        self.assertEqual(configuration, "[Interface]\nPrivateKey = test\n")
        self.assertEqual(
            session.request.await_args_list,
            [
                call("GET", "https://wg.example/api/wireguard/client"),
                call(
                    "POST",
                    "https://wg.example/api/wireguard/client",
                    json={"name": "ZENITH-87654321"},
                ),
                call(
                    "GET",
                    "https://wg.example/api/wireguard/client/42/configuration",
                ),
                call(
                    "DELETE",
                    "https://wg.example/api/wireguard/client/42",
                ),
            ],
        )

    async def test_configuration_must_exist_and_be_non_empty(self):
        missing_server = SimpleNamespace(get_clients=AsyncMock(return_value=[]))
        with self.assertRaises(wg_api.WireGuardClientNotFound):
            await wg_api.get_client_configuration_by_name(missing_server, "ZENITH-12345678")

        empty_client = SimpleNamespace(
            name="ZENITH-12345678",
            get_configuration=AsyncMock(return_value=""),
        )
        empty_server = SimpleNamespace(get_clients=AsyncMock(return_value=[empty_client]))
        with self.assertRaises(wg_api.WireGuardError):
            await wg_api.get_client_configuration_by_name(empty_server, "ZENITH-12345678")

    async def test_configuration_is_saved_as_utf8(self):
        client = SimpleNamespace(
            name="ZENITH-12345678",
            get_configuration=AsyncMock(return_value="[Interface]\nPrivateKey = test\n"),
        )
        server = SimpleNamespace(get_clients=AsyncMock(return_value=[client]))

        target = MagicMock(spec=Path)
        target.__str__.return_value = "ZENITH-12345678.conf"
        temporary = MagicMock(spec=Path)
        target.with_suffix.return_value = temporary
        config_directory = MagicMock(spec=Path)
        with (
            patch.object(wg_api, "CONFIG_DIR", config_directory),
            patch.object(wg_api, "config_file_path", return_value=target),
        ):
            result = await wg_api.save_client_configuration(
                server,
                "ZENITH-12345678",
            )

        self.assertEqual(result, "ZENITH-12345678.conf")
        temporary.write_text.assert_called_once_with(
            "[Interface]\nPrivateKey = test\n",
            encoding="utf-8",
            newline="\n",
        )
        temporary.replace.assert_called_once_with(target)

    async def test_provisioning_enforces_capacity_limit(self):
        existing_client = SimpleNamespace(name="ANOTHER", uid="1")
        server = SimpleNamespace(
            get_clients=AsyncMock(return_value=[existing_client]),
            create_client=AsyncMock(),
            remove_client=AsyncMock(),
        )

        async def run_action(url, password, action):
            return await action(server)

        with (
            patch.object(wg_api, "_with_server", side_effect=run_action),
            patch.object(wg_api, "wg_max_clients", return_value=1),
        ):
            with self.assertRaises(wg_api.WireGuardCapacityError):
                await wg_api.provision_client_wg(
                    "ZENITH-87654321",
                    "https://127.0.0.1:51821",
                    "secret",
                )

        server.create_client.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
