import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler


SCHEDULER_TZ = "Europe/Moscow"

_scheduler: AsyncIOScheduler | None = None
_logger = logging.getLogger(__name__)


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler

    if _scheduler is None:
        _scheduler = AsyncIOScheduler(
            timezone=SCHEDULER_TZ,
            job_defaults={
                "coalesce": True,
                "max_instances": 1,
                "misfire_grace_time": 3600,
            },
        )
        _logger.info("Scheduler created (timezone=%s).", SCHEDULER_TZ)

    if not _scheduler.running:
        _scheduler.start()
        _logger.info("Scheduler started.")

    return _scheduler
