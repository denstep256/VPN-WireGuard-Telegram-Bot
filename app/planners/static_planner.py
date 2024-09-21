from aiogram import Bot
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select, update
from app.database.models import async_session, User, Static

async def update_static(bot: Bot):
    async with async_session() as session:
        # Запрос всех пользователей, у которых is_active_subs и is_active_trial == 0
        query = select(User).where(User.is_active_subs == 0, User.is_active_trial == 0)
        result = await session.execute(query)
        inactive_users = result.scalars().all()

        for user in inactive_users:
            # Проверка, что пользователя нет в таблице Static
            static_query = select(Static).where(Static.tg_id == user.tg_id)
            static_result = await session.execute(static_query)
            user_in_static = static_result.scalar_one_or_none()

            if not user_in_static:
                # Если пользователя нет в Static, добавляем его
                new_static_user = Static(
                    tg_id=user.tg_id,
                    username=user.username,
                    use_trial=user.use_trial,  # Взято из таблицы User
                    use_subs=user.use_subs # Взято из таблицы User
                )
                session.add(new_static_user)

        # Применяем изменения в базе данных
        await session.commit()



# Настройка планировщика
def setup_scheduler_update_static(bot: Bot):

    # Инициализация планировщика
    scheduler = AsyncIOScheduler(timezone='Europe/Moscow')

    # Настройка задачи для проверки подписок (например, раз в день)
    scheduler.add_job(
        update_static,
        trigger=IntervalTrigger(seconds=10),  # Задаём интервал выполнения
        id='update_static',
        kwargs={'bot': bot},
        replace_existing=True
    )

    # Запуск планировщика
    scheduler.start()