from __future__ import annotations

from collections.abc import Iterable

import config

from app.paths import CONFIG_DIR, LOGS_DIR


def wg_max_clients() -> int:
    return int(getattr(config, "WG_MAX_CLIENTS", 60))


def wg_request_timeout_seconds() -> float:
    return float(getattr(config, "WG_REQUEST_TIMEOUT_SECONDS", 15))


def _missing_or_blank(names: Iterable[str]) -> list[str]:
    return [name for name in names if not str(getattr(config, name, "")).strip()]


def validate_runtime_config() -> None:
    errors: list[str] = []

    missing = _missing_or_blank(
        (
            "TOKEN",
            "DB_URL_USERS",
            "PAYMENT_TOKEN",
            "ADMIN_ID",
            "one_mounth_price",
            "six_mounth_price",
            "twelve_mounth_price",
        )
    )
    if missing:
        errors.append("не заданы обязательные параметры: " + ", ".join(missing))

    try:
        admin_id = int(getattr(config, "ADMIN_ID", 0))
        if admin_id <= 0:
            raise ValueError
    except (TypeError, ValueError):
        errors.append("ADMIN_ID должен быть положительным целым числом")

    for name in (
        "one_mounth_price",
        "six_mounth_price",
        "twelve_mounth_price",
    ):
        try:
            if int(getattr(config, name, 0)) <= 0:
                raise ValueError
        except (TypeError, ValueError):
            errors.append(f"{name} должен быть положительным целым числом")

    try:
        if int(getattr(config, "MIN_PAY_RUB", 50)) <= 0:
            raise ValueError
    except (TypeError, ValueError):
        errors.append("MIN_PAY_RUB должен быть положительным целым числом")

    try:
        if wg_max_clients() <= 0:
            raise ValueError
    except (TypeError, ValueError):
        errors.append("WG_MAX_CLIENTS должен быть положительным целым числом")

    try:
        if wg_request_timeout_seconds() <= 0:
            raise ValueError
    except (TypeError, ValueError):
        errors.append("WG_REQUEST_TIMEOUT_SECONDS должен быть положительным числом")

    if errors:
        formatted = "\n - ".join(errors)
        raise RuntimeError(f"Некорректная конфигурация приложения:\n - {formatted}")


def ensure_runtime_directories() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
