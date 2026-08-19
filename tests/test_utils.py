import unittest
from datetime import date
import re
from unittest.mock import patch

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.addons import utilits as utilits_module
from app.addons.utilits import (
    add_months,
    calculate_expiry_date,
    determine_subscription_type,
    generate_client_name,
    parse_date_value,
    server_api_url,
    to_iso_date,
)
from app.database.models import Base, Subscribers, TestPeriod
from app.paths import BASE_DIR, config_file_path, resolve_database_url
from app.wg_api.wg_api import validate_client_name


class UtilityTests(unittest.TestCase):
    def test_calendar_months_handle_month_end_and_leap_year(self):
        self.assertEqual(add_months(date(2024, 1, 31), 1), date(2024, 2, 29))
        self.assertEqual(add_months(date(2025, 1, 31), 1), date(2025, 2, 28))
        self.assertEqual(add_months(date(2025, 12, 31), 1), date(2026, 1, 31))

    def test_subscription_expiry_uses_calendar_months(self):
        self.assertEqual(
            calculate_expiry_date("semi_annual_subs", start=date(2025, 8, 31)),
            date(2026, 2, 28),
        )
        with self.assertRaises(ValueError):
            calculate_expiry_date("invalid", start=date(2025, 1, 1))

    def test_date_parsing_is_explicit(self):
        self.assertEqual(parse_date_value("2026-08-19"), date(2026, 8, 19))
        self.assertEqual(to_iso_date(date(2026, 8, 19)), "2026-08-19")
        with self.assertRaises(ValueError):
            to_iso_date("not-a-date")

    def test_manual_subscription_type_is_not_mislabeled(self):
        self.assertEqual(determine_subscription_type(1), "monthly_subs")
        self.assertEqual(determine_subscription_type(3), "manual_3_months")
        self.assertEqual(determine_subscription_type(6), "semi_annual_subs")

    def test_client_name_and_config_path_are_safe(self):
        self.assertEqual(validate_client_name("ZENITH-12345678"), "ZENITH-12345678")
        with self.assertRaises(ValueError):
            validate_client_name("../secret")
        with self.assertRaises(ValueError):
            config_file_path("../secret")
        self.assertEqual(config_file_path("client.conf").name, "client.conf")
        self.assertEqual(config_file_path("client").name, "client.conf")
        self.assertRegex(generate_client_name(), re.compile(r"^ZENITH-[0-9]{6}$"))

    def test_relative_sqlite_database_is_resolved_from_project_root(self):
        expected = (BASE_DIR / "db.sqlite3").resolve().as_posix()
        self.assertEqual(
            resolve_database_url("sqlite+aiosqlite:///db.sqlite3"),
            f"sqlite+aiosqlite:///{expected}",
        )
        self.assertEqual(
            resolve_database_url("sqlite+aiosqlite:///:memory:"),
            "sqlite+aiosqlite:///:memory:",
        )

    def test_server_api_url_uses_ipv4_host_and_port(self):
        ipv4 = type("Server", (), {"host_ip": "127.0.0.1", "port": "51821"})()
        self.assertEqual(server_api_url(ipv4), "https://127.0.0.1:51821")


class UniqueClientNameTests(unittest.IsolatedAsyncioTestCase):
    async def test_name_collision_is_checked_across_paid_and_trial_subscriptions(self):
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            async with sessions() as session:
                session.add(
                    Subscribers(
                        tg_id=1,
                        username="paid",
                        file_name="ZENITH-000001",
                        subscription="monthly_subs",
                        expiry_date="2026-09-19",
                        server_region="Amsterdam",
                        server_region_id=1,
                        notif_oneday=False,
                        note="",
                    )
                )
                session.add(
                    TestPeriod(
                        tg_id=2,
                        username="trial",
                        file_name="ZENITH-000002",
                        subscription="trial",
                        expiry_date="2026-08-22",
                        notif_oneday=False,
                        server_region="Amsterdam",
                        server_region_id=1,
                    )
                )
                await session.commit()

                with patch.object(
                    utilits_module,
                    "generate_client_name",
                    side_effect=("ZENITH-000001", "ZENITH-000002", "ZENITH-000003"),
                ):
                    generated = await utilits_module.generate_unique_client_name(session)
                self.assertEqual(generated, "ZENITH-000003")
        finally:
            await engine.dispose()


if __name__ == "__main__":
    unittest.main()
