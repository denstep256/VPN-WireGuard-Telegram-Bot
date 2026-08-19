import unittest

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.admin.admin_commands_add_server import _next_region_id
from app.database.models import Base, Server


class AdminServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def test_region_id_is_incremented_inside_region(self):
        async with self.sessions() as session:
            self.assertEqual(await _next_region_id(session, "Amsterdam"), 1)
            session.add_all(
                [
                    Server(
                        region="Amsterdam",
                        region_id=1,
                        host_ip="10.0.0.1",
                        port="51821",
                        password="secret",
                        date="2026-08-19",
                        is_active=True,
                    ),
                    Server(
                        region="Amsterdam",
                        region_id=3,
                        host_ip="10.0.0.3",
                        port="51821",
                        password="secret",
                        date="2026-08-19",
                        is_active=True,
                    ),
                    Server(
                        region="Helsinki",
                        region_id=8,
                        host_ip="10.0.1.8",
                        port="51821",
                        password="secret",
                        date="2026-08-19",
                        is_active=True,
                    ),
                ]
            )
            await session.commit()

            self.assertEqual(await _next_region_id(session, "Amsterdam"), 4)
            self.assertEqual(await _next_region_id(session, "Helsinki"), 9)
            self.assertEqual(await _next_region_id(session, "Warsaw"), 1)


if __name__ == "__main__":
    unittest.main()
