import config
import asyncio

from app.admin.admin_commands_add_server import admin_command_add_server_router
from app.admin.admin_commands_pinger import admin_pinger_router
from app.database.models import async_main

from aiogram import Bot, Dispatcher

from app.payments.renew_subs import renew_pay_router
from app.users.buy_handler import user_buy_router
from app.users.handlers import router
from app.admin.admin_handlers import admin_router
from app.payments.payments import pay_router
from app.users.invite_handler import invite_router
from app.users.promo_handler import promocode_router
from app.users.renew_handler import user_renew_router
from app.users.trial import trial_router
from app.admin.admin_commands_sender import admin_command_router
from app.admin.admin_subs_manager import admin_subs_router

from app.planners.static_planner import setup_scheduler_update_static
from app.planners.subscribers.notif_end_day_subs import setup_scheduler_subs_notif_end_day
from app.planners.subscribers.notof_oneday_subs import setup_scheduler_subs_notif_oneday
from app.planners.trial_planner.notif_end_day import setup_scheduler_trial_notif_end_day
from app.planners.trial_planner.notif_oneday import setup_scheduler_trial_notif_oneday



async def main():
    await async_main()
    #Включение бота
    bot = Bot(token=config.TOKEN)
    dp = Dispatcher()

    # Настройка планировщиков
    setup_scheduler_trial_notif_oneday(bot)
    setup_scheduler_trial_notif_end_day(bot)
    setup_scheduler_subs_notif_oneday(bot)
    setup_scheduler_subs_notif_end_day(bot)
    setup_scheduler_update_static(bot)


    #Настройка Router
    dp.include_router(router)
    dp.include_router(pay_router)
    dp.include_router(renew_pay_router)
    dp.include_router(trial_router)
    dp.include_router(invite_router)
    dp.include_router(promocode_router)
    dp.include_router(user_renew_router)
    dp.include_router(user_buy_router)
    dp.include_router(admin_router)
    dp.include_router(admin_command_router)
    dp.include_router(admin_command_add_server_router)
    dp.include_router(admin_subs_router)
    dp.include_router(admin_pinger_router)

    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())


