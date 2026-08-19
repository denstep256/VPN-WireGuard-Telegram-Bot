import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from app.paths import LOGS_DIR


class _PrefixFilter(logging.Filter):
    def __init__(self, *prefixes: str):
        super().__init__()
        self.prefixes = prefixes

    def filter(self, record: logging.LogRecord) -> bool:
        for prefix in self.prefixes:
            if record.name == prefix or record.name.startswith(f"{prefix}."):
                return True
        return False


def _build_file_handler(
    path: Path,
    formatter: logging.Formatter,
    *,
    level: int = logging.INFO,
    filters: tuple[_PrefixFilter, ...] = (),
) -> TimedRotatingFileHandler:
    handler = TimedRotatingFileHandler(
        path,
        when="midnight",
        interval=1,
        backupCount=14,
        encoding="utf-8",
    )
    handler._vpn_bot_file_handler = True  # type: ignore[attr-defined]
    handler.setLevel(level)
    handler.setFormatter(formatter)
    for log_filter in filters:
        handler.addFilter(log_filter)
    return handler


def setup_logging() -> None:
    logs_dir = LOGS_DIR
    logs_dir.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()

    if any(getattr(handler, "_vpn_bot_file_handler", False) for handler in root_logger.handlers):
        return

    root_logger.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    admin_handler = _build_file_handler(
        logs_dir / "admin.log",
        formatter,
        filters=(_PrefixFilter("app.admin"),),
    )
    payments_handler = _build_file_handler(
        logs_dir / "payments.log",
        formatter,
        filters=(_PrefixFilter("app.payments"),),
    )
    database_handler = _build_file_handler(
        logs_dir / "database.log",
        formatter,
        filters=(_PrefixFilter("app.database"),),
    )
    scheduler_handler = _build_file_handler(
        logs_dir / "scheduler.log",
        formatter,
        filters=(_PrefixFilter("app.planners"),),
    )
    bot_handler = _build_file_handler(
        logs_dir / "bot.log",
        formatter,
        level=logging.ERROR,
    )
    bot_handler._vpn_bot_main_errors = True  # type: ignore[attr-defined]

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(formatter)

    root_logger.addHandler(admin_handler)
    root_logger.addHandler(payments_handler)
    root_logger.addHandler(database_handler)
    root_logger.addHandler(scheduler_handler)
    root_logger.addHandler(bot_handler)
    root_logger.addHandler(stream_handler)

    logging.getLogger("aiogram").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
