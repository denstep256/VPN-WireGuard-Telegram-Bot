import config
import asyncio

from aiogram import Bot, Dispatcher

from app.admin.admin_handlers import admin_router
from app.users.handlers import router
from app.planners.notification import setup_send_notifications
from app.payments.payments import pay_router
from app.planners.trial_planner.notif_end_day import setup_scheduler_trial_notif_end_day
from app.planners.trial_planner.notif_oneday import setup_scheduler_trial_notif_oneday
from app.users.trial import trial_router
from app.database.models import async_main
from app.planners.subscribers import setup_update_scheduler


async def main():
    await async_main()
    #Включение бота
    bot = Bot(token=config.TOKEN)
    dp = Dispatcher()

    # Настройка планировщиков
    setup_update_scheduler(bot)
    setup_send_notifications(bot)
    setup_scheduler_trial_notif_oneday(bot)
    setup_scheduler_trial_notif_end_day(bot)

    #Настройка Router
    dp.include_router(router)
    dp.include_router(pay_router)
    dp.include_router(trial_router)
    dp.include_router(admin_router)

    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
