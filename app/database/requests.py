from app.database.models import async_session
from app.database.models import User, TestPeriod, Subscribers
from sqlalchemy import select


async def set_user(tg_id, username, first_name, date_add):
    async with async_session() as session:
        user = await session.scalar(select(User.tg_id == tg_id))
        if not user:
            session.add(User(tg_id=tg_id, username=username, first_name=first_name, date_add=date_add))
            await session.commit()


