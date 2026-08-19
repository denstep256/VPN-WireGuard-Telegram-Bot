import unittest
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.models import Base, Server, Subscribers, TestPeriod
from app.planners.subscribers import notif_end_day_subs
from app.planners.trial_planner import notif_end_day


class FakeBot:
    def __init__(self):
        self.messages = []

    async def send_message(self, **kwargs):
        self.messages.append(kwargs)


class PlannerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def _add_server(self, region: str, region_id: int, host: str):
        async with self.sessions() as session:
            server = Server(
                region=region,
                region_id=region_id,
                host_ip=host,
                port="51821",
                password="secret",
                date="2026-08-19",
                is_active=True,
            )
            session.add(server)
            await session.commit()

    async def test_subscription_cleanup_retries_without_duplicate_notification(self):
        await self._add_server("Amsterdam", 1, "10.0.0.1")
        async with self.sessions() as session:
            subscriber = Subscribers(
                tg_id=101,
                username="tester",
                file_name="ZENITH-10101010",
                subscription="monthly_subs",
                expiry_date=(date.today() - timedelta(days=1)).isoformat(),
                server_region="Amsterdam",
                server_region_id=1,
                notif_oneday=True,
                note="",
            )
            session.add(subscriber)
            await session.commit()
            await session.refresh(subscriber)
            subscriber_id = subscriber.id

        bot = FakeBot()
        remove_client = AsyncMock(side_effect=[RuntimeError("offline"), True])
        with (
            patch.object(notif_end_day_subs, "async_session", self.sessions),
            patch.object(notif_end_day_subs, "remove_client_wg", remove_client),
            patch.object(notif_end_day_subs, "delete_file_by_name", return_value=False),
        ):
            with self.assertLogs(notif_end_day_subs.logger, level="ERROR"):
                await notif_end_day_subs.check_subscriptions_subs(bot)
            await notif_end_day_subs.check_subscriptions_subs(bot)

        async with self.sessions() as session:
            stored = await session.get(Subscribers, subscriber_id)

        self.assertEqual(len(bot.messages), 1)
        self.assertTrue(stored.note.startswith("expired_cleaned:"))
        self.assertEqual(remove_client.await_count, 2)

    async def test_trial_cleanup_uses_stored_server_only(self):
        await self._add_server("Amsterdam", 1, "10.0.0.1")
        await self._add_server("Helsinki", 2, "10.0.0.2")
        async with self.sessions() as session:
            trial = TestPeriod(
                tg_id=202,
                username="tester",
                file_name="ZENITH-20202020",
                subscription="trial",
                expiry_date=date.today().isoformat(),
                notif_oneday=True,
                server_region="Helsinki",
                server_region_id=2,
            )
            session.add(trial)
            await session.commit()
            await session.refresh(trial)
            trial_id = trial.id

        bot = FakeBot()
        remove_client = AsyncMock(return_value=True)
        with (
            patch.object(notif_end_day, "async_session", self.sessions),
            patch.object(notif_end_day, "remove_client_wg", remove_client),
            patch.object(notif_end_day, "delete_file_by_name", return_value=False),
        ):
            await notif_end_day.check_subscriptions_trial(bot)

        async with self.sessions() as session:
            stored = await session.get(TestPeriod, trial_id)

        self.assertEqual(stored.subscription, "trial_used")
        remove_client.assert_awaited_once()
        self.assertIn("10.0.0.2", remove_client.await_args.args[1])

    async def test_expired_pending_trial_is_cleaned_and_released(self):
        await self._add_server("Amsterdam", 1, "10.0.0.1")
        async with self.sessions() as session:
            trial = TestPeriod(
                tg_id=303,
                username="tester",
                file_name="ZENITH-30303030",
                subscription="trial_pending",
                expiry_date=(date.today() - timedelta(days=1)).isoformat(),
                notif_oneday=False,
                server_region="Amsterdam",
                server_region_id=1,
            )
            session.add(trial)
            await session.commit()
            await session.refresh(trial)
            trial_id = trial.id

        bot = FakeBot()
        remove_client = AsyncMock(return_value=True)
        with (
            patch.object(notif_end_day, "async_session", self.sessions),
            patch.object(notif_end_day, "remove_client_wg", remove_client),
            patch.object(notif_end_day, "delete_file_by_name", return_value=False),
        ):
            await notif_end_day.check_subscriptions_trial(bot)

        async with self.sessions() as session:
            stored = await session.get(TestPeriod, trial_id)

        self.assertIsNone(stored)
        self.assertEqual(bot.messages, [])
        remove_client.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
