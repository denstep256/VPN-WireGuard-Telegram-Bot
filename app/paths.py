from pathlib import Path
import re

import config


BASE_DIR = Path(__file__).resolve().parent.parent
APP_DIR = BASE_DIR / "app"
TEXTS_PATH = APP_DIR / "addons" / "texts.json"
_CLIENT_FILE_STEM_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


def _resolve_from_base(value: str | Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = BASE_DIR / path
    return path.resolve()


CONFIG_DIR = _resolve_from_base(getattr(config, "DIR_CONF", APP_DIR / "auth"))
LOGS_DIR = BASE_DIR / "logs"


def resolve_database_url(url: str) -> str:
    prefix = "sqlite+aiosqlite:///"
    normalized = str(url or "").strip()
    if not normalized.startswith(prefix):
        return normalized

    database_path = normalized.removeprefix(prefix)
    if database_path == ":memory:" or database_path.startswith("file:"):
        return normalized

    path = Path(database_path).expanduser()
    if not path.is_absolute():
        path = BASE_DIR / path
    return f"{prefix}{path.resolve().as_posix()}"


def config_file_path(client_name: str) -> Path:
    raw_name = str(client_name or "").strip()
    stem = raw_name[:-5] if raw_name.endswith(".conf") else raw_name
    if not _CLIENT_FILE_STEM_RE.fullmatch(stem):
        raise ValueError("Invalid WireGuard client configuration file name")
    return CONFIG_DIR / f"{stem}.conf"
