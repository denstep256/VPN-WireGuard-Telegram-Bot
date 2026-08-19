import unittest

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.admin.admin_commands_add_promocode import _resolve_promo_owner
from app.database.models import Base, User


class AdminPromoCodeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with self.sessions() as session:
            session.add(
                User(
                    tg_id=123456789,
                    username="Test_User",
                    first_name="Test",
                    bonus_balance=0,
                    date="2026-08-19",
                )
            )
            await session.commit()

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def test_owner_can_be_resolved_by_id_or_username(self):
        async with self.sessions() as session:
            by_id = await _resolve_promo_owner(session, "123456789")
            by_username = await _resolve_promo_owner(session, "@test_user")
            without_at = await _resolve_promo_owner(session, "TEST_USER")
            common = await _resolve_promo_owner(session, "0")

        self.assertEqual(by_id[0], 123456789)
        self.assertEqual(by_username[0], 123456789)
        self.assertEqual(without_at[0], 123456789)
        self.assertEqual(common, (None, "общий"))

    async def test_unknown_owner_is_rejected(self):
        async with self.sessions() as session:
            with self.assertRaises(ValueError):
                await _resolve_promo_owner(session, "@missing_user")
            with self.assertRaises(ValueError):
                await _resolve_promo_owner(session, "999999999")


if __name__ == "__main__":
    unittest.main()
