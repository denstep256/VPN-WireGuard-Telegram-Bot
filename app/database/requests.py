from app.database.models import async_session
from app.database.models import User
from sqlalchemy import select


async def set_user_start(tg_id, username, first_name, date_add):
    async with async_session() as session:
        query = select(User).where(User.tg_id == tg_id)
        result = await session.execute(query)
        user_in_user = result.scalar_one_or_none()

        if not user_in_user:
            new_user = User(
                tg_id=tg_id,
                username=username,
                first_name=first_name,
                date_add=date_add,
            )
            session.add(new_user)
            await session.commit()