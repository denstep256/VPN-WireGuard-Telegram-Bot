import unittest
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.addons.utilits import add_months
from app.database.models import Base, Payments, Server, Subscribers, User
from app.payments import payments as purchase_module
from app.payments import renew_subs as renewal_module
from app.payments.pricing import (
    build_buy_payload,
    build_renew_payload,
    calculate_invoice_price,
)
from app.time_utils import moscow_today


class FakeBot:
    def __init__(self):
        self.messages = []

    async def send_message(self, chat_id, text, **kwargs):
        self.messages.append((chat_id, text, kwargs))


class FakeMessage:
    def __init__(self, *, tg_id: int, username: str, payment):
        self.from_user = SimpleNamespace(id=tg_id, username=username)
        self.successful_payment = payment
        self.bot = FakeBot()
        self.answers = []
        self.documents = []

    async def answer(self, text, **kwargs):
        self.answers.append((text, kwargs))

    async def answer_document(self, document, **kwargs):
        self.documents.append((document, kwargs))


def successful_payment(payload: str, total_rub: int, charge_id: str):
    return SimpleNamespace(
        invoice_payload=payload,
        total_amount=total_rub * 100,
        currency="RUB",
        provider_payment_charge_id=charge_id,
    )


class PaymentFlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def _add_user_and_server(self, tg_id: int = 101):
        async with self.sessions() as session:
            session.add(
                User(
                    tg_id=tg_id,
                    username="tester",
                    first_name="Test",
                    bonus_balance=0,
                    date="2026-08-19",
                )
            )
            session.add(
                Server(
                    region="Amsterdam",
                    region_id=1,
                    host_ip="127.0.0.1",
                    port="51821",
                    password="secret",
                    date="2026-08-19",
                    is_active=True,
                )
            )
            await session.commit()

    async def test_purchase_success_is_idempotent(self):
        await self._add_user_and_server()
        payload = build_buy_payload("monthly_subs", "Amsterdam", 1, 0, 0)
        payment = successful_payment(
            payload,
            calculate_invoice_price("monthly_subs", 0, 0),
            "charge-purchase-1",
        )
        message = FakeMessage(tg_id=101, username="tester", payment=payment)
        provision = AsyncMock(return_value="app/auth/ZENITH-test.conf")

        with (
            patch.object(purchase_module, "async_session", self.sessions),
            patch.object(purchase_module, "provision_client_wg", provision),
        ):
            await purchase_module.handle_successful_payment(message)
            await purchase_module.handle_successful_payment(message)

        async with self.sessions() as session:
            payment_count = await session.scalar(select(func.count(Payments.id)))
            subscribers = list((await session.scalars(select(Subscribers))).all())

        self.assertEqual(payment_count, 1)
        self.assertEqual(len(subscribers), 1)
        self.assertEqual(subscribers[0].note, "payment:charge-purchase-1:completed")
        provision.assert_awaited_once()
        self.assertTrue(any("уже обработан" in text for text, _ in message.answers))

    async def test_purchase_is_persisted_while_server_is_unavailable(self):
        await self._add_user_and_server(tg_id=111)
        async with self.sessions() as session:
            server = await session.scalar(select(Server))
            server.is_active = False
            await session.commit()

        payload = build_buy_payload("monthly_subs", "Amsterdam", 1, 0, 0)
        payment = successful_payment(
            payload,
            calculate_invoice_price("monthly_subs", 0, 0),
            "charge-purchase-pending-server",
        )
        message = FakeMessage(tg_id=111, username="tester", payment=payment)
        provision = AsyncMock(return_value="app/auth/ZENITH-pending.conf")

        with (
            patch.object(purchase_module, "async_session", self.sessions),
            patch.object(purchase_module, "provision_client_wg", provision),
        ):
            with self.assertLogs(purchase_module.logger, level="ERROR"):
                await purchase_module.handle_successful_payment(message)
            provision.assert_not_awaited()

            async with self.sessions() as session:
                payment_count = await session.scalar(select(func.count(Payments.id)))
                subscriber = await session.scalar(select(Subscribers))
                server = await session.scalar(select(Server))
                self.assertEqual(payment_count, 1)
                self.assertEqual(
                    subscriber.note,
                    "payment:charge-purchase-pending-server:pending",
                )
                server.is_active = True
                await session.commit()

            await purchase_module.handle_successful_payment(message)

        provision.assert_awaited_once()
        async with self.sessions() as session:
            subscriber = await session.scalar(select(Subscribers))
        self.assertEqual(
            subscriber.note,
            "payment:charge-purchase-pending-server:completed",
        )

    async def test_purchase_without_user_is_still_recorded(self):
        payload = build_buy_payload("monthly_subs", "Amsterdam", 1, 0, 0)
        payment = successful_payment(
            payload,
            calculate_invoice_price("monthly_subs", 0, 0),
            "charge-purchase-missing-user",
        )
        message = FakeMessage(tg_id=404, username="missing", payment=payment)

        with (
            patch.object(purchase_module, "async_session", self.sessions),
            self.assertLogs(purchase_module.logger, level="CRITICAL"),
        ):
            await purchase_module.handle_successful_payment(message)

        async with self.sessions() as session:
            stored = await session.scalar(
                select(Payments).where(
                    Payments.provider_payment_charge_id
                    == "charge-purchase-missing-user"
                )
            )
        self.assertIsNotNone(stored)

    async def test_renewal_success_extends_only_once(self):
        await self._add_user_and_server(tg_id=202)
        initial_expiry = date.today() + timedelta(days=10)
        async with self.sessions() as session:
            subscriber = Subscribers(
                tg_id=202,
                username="tester",
                file_name="ZENITH-20202020",
                subscription="monthly_subs",
                expiry_date=initial_expiry.isoformat(),
                server_region="Amsterdam",
                server_region_id=1,
                notif_oneday=False,
                note="",
            )
            session.add(subscriber)
            await session.commit()
            await session.refresh(subscriber)
            sub_id = subscriber.id

        payload = build_renew_payload("monthly_subs", sub_id, 0, 0)
        payment = successful_payment(
            payload,
            calculate_invoice_price("monthly_subs", 0, 0),
            "charge-renewal-1",
        )
        message = FakeMessage(tg_id=202, username="tester", payment=payment)

        with patch.object(renewal_module, "async_session", self.sessions):
            await renewal_module.handle_renew_success(message)
            await renewal_module.handle_renew_success(message)

        async with self.sessions() as session:
            stored_subscriber = await session.get(Subscribers, sub_id)
            payment_count = await session.scalar(select(func.count(Payments.id)))

        self.assertEqual(payment_count, 1)
        self.assertEqual(
            stored_subscriber.expiry_date,
            add_months(initial_expiry, 1).isoformat(),
        )
        self.assertEqual(
            stored_subscriber.note,
            "renewal:charge-renewal-1:completed",
        )
        self.assertTrue(any("уже обработано" in text for text, _ in message.answers))

    async def test_renewal_restores_config_cleaned_on_expiry_day(self):
        await self._add_user_and_server(tg_id=303)
        async with self.sessions() as session:
            subscriber = Subscribers(
                tg_id=303,
                username="tester",
                file_name="ZENITH-30303030",
                subscription="monthly_subs",
                expiry_date=moscow_today().isoformat(),
                server_region="Amsterdam",
                server_region_id=1,
                notif_oneday=True,
                note=f"expired_cleaned:{moscow_today().isoformat()}",
            )
            session.add(subscriber)
            await session.commit()
            await session.refresh(subscriber)
            sub_id = subscriber.id

        payload = build_renew_payload("monthly_subs", sub_id, 0, 0)
        payment = successful_payment(
            payload,
            calculate_invoice_price("monthly_subs", 0, 0),
            "charge-renewal-restore",
        )
        message = FakeMessage(tg_id=303, username="tester", payment=payment)
        provision = AsyncMock(return_value="app/auth/ZENITH-30303030.conf")

        with (
            patch.object(renewal_module, "async_session", self.sessions),
            patch.object(renewal_module, "provision_client_wg", provision),
        ):
            await renewal_module.handle_renew_success(message)

        provision.assert_awaited_once()
        async with self.sessions() as session:
            stored_subscriber = await session.get(Subscribers, sub_id)
        self.assertEqual(
            stored_subscriber.note,
            "renewal:charge-renewal-restore:completed",
        )

    async def test_renewal_without_subscription_is_still_recorded(self):
        payload = build_renew_payload("monthly_subs", 999999, 0, 0)
        payment = successful_payment(
            payload,
            calculate_invoice_price("monthly_subs", 0, 0),
            "charge-renewal-missing-subscription",
        )
        message = FakeMessage(tg_id=505, username="missing", payment=payment)

        with (
            patch.object(renewal_module, "async_session", self.sessions),
            self.assertLogs(renewal_module.logger, level="CRITICAL"),
        ):
            await renewal_module.handle_renew_success(message)

        async with self.sessions() as session:
            stored = await session.scalar(
                select(Payments).where(
                    Payments.provider_payment_charge_id
                    == "charge-renewal-missing-subscription"
                )
            )
        self.assertIsNotNone(stored)


if __name__ == "__main__":
    unittest.main()
