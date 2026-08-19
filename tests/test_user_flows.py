import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.models import Base, Server
from app.users import buy_handler


class UserFlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def test_server_selection_edits_text_without_image_asset(self):
        async with self.sessions() as session:
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

        callback = SimpleNamespace(
            data="srv|Amsterdam|1",
            from_user=SimpleNamespace(id=101),
            message=SimpleNamespace(edit_text=AsyncMock()),
            answer=AsyncMock(),
        )

        with patch.object(buy_handler, "async_session", self.sessions):
            await buy_handler.handle_server_selection(callback)

        callback.message.edit_text.assert_awaited_once()
        callback.answer.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
