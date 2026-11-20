"""Add VLESS to current subscriptions in a SQLite database."""
import argparse
import asyncio
import logging
import sqlite3
from contextlib import closing
from datetime import date, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import config
from app.database.models import Subscribers, TestPeriod, _run_lightweight_migrations, refresh_user_protocol
from app.vpn.provisioning import PROTOCOL_BOTH, PROTOCOL_WIREGUARD, wireguard_settings
from app.xui_api.xui_api import XUIClient, expiry_to_ms

logger = logging.getLogger(__name__)


def readonly_database(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)


def count_candidates(path: Path, today: date) -> tuple[int, int]:
    counts = []
    with closing(readonly_database(path)) as connection:
        for table, eligibility in (("subscribers", "1=1"), ("test_period", "subscription='trial'")):
            columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
            if "protocol" in columns:
                eligibility += " AND COALESCE(protocol, 'wireguard')='wireguard'"
            if "provisioned" in columns:
                eligibility += " AND provisioned=1"
            count, = connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {eligibility} AND date(expiry_date)>=?",
                (today.isoformat(),),
            ).fetchone()
            counts.append(count)
    return tuple(counts)


def backup_database(path: Path) -> Path:
    with NamedTemporaryFile(dir=path.parent, prefix=f"{path.stem}-backup-", suffix=".sqlite3", delete=False) as backup:
        backup_path = Path(backup.name)
    with closing(readonly_database(path)) as source, closing(sqlite3.connect(backup_path)) as destination:
        source.backup(destination)
    return backup_path


async def migrate(path: Path, today: date) -> int:
    wireguard_settings()
    engine = create_async_engine(URL.create("sqlite+aiosqlite", database=str(path)))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    failed = 0
    changed = 0
    try:
        async with XUIClient.connect() as panel:
            inbound_ids = await panel.get_target_inbound_ids()
            await panel.subscription_base_url()
            print(f"Резервная копия создана: {backup_database(path)}", flush=True)
            async with engine.begin() as connection:
                await _run_lightweight_migrations(connection)

            for model, eligibility in (
                (Subscribers, Subscribers.provisioned.is_(True)),
                (TestPeriod, TestPeriod.subscription == "trial"),
            ):
                async with sessions() as session:
                    ids = (await session.scalars(select(model.id).where(
                        eligibility, func.coalesce(model.protocol, PROTOCOL_WIREGUARD) == PROTOCOL_WIREGUARD,
                        func.date(model.expiry_date) >= today.isoformat(),
                    ).order_by(model.id))).all()
                for record_id in ids:
                    try:
                        async with sessions.begin() as session:
                            await session.execute(text("BEGIN IMMEDIATE"))
                            record = await session.get(model, record_id)
                            if not record or (record.protocol or PROTOCOL_WIREGUARD) != PROTOCOL_WIREGUARD:
                                continue
                            if expiry_to_ms(record.expiry_date) <= int(datetime.now().timestamp() * 1000):
                                continue
                            record.xui_sub_id = await panel.ensure_client(
                                email=record.file_name, expiry=record.expiry_date,
                                tg_id=record.tg_id, username=record.username,
                                sub_id=record.xui_sub_id, inbound_ids=inbound_ids,
                            )
                            record.protocol = PROTOCOL_BOTH
                            await refresh_user_protocol(session, record.tg_id)
                        changed += 1
                    except Exception as exc:
                        failed += 1
                        logger.error("%s #%s: %s", model.__tablename__, record_id, exc)

            if not failed:
                async with engine.begin() as connection:
                    await connection.execute(text("PRAGMA secure_delete=ON"))
                    await connection.execute(text("DROP TABLE IF EXISTS servers"))
            async with sessions.begin() as session:
                await refresh_user_protocol(session)
    finally:
        await engine.dispose()
    print(f"Добавлен VLESS к {changed} подпискам. Ошибок: {failed}.")
    return int(bool(failed))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path, help="Путь к существующей SQLite БД.")
    parser.add_argument("--apply", action="store_true", help="Создать резервную копию и применить изменения.")
    args = parser.parse_args()
    path = args.db.expanduser().resolve()
    if not path.is_file():
        parser.error("Указанная база не существует.")
    today = datetime.now(ZoneInfo(config.VPN_TIMEZONE)).date()
    paid, trial = count_candidates(path, today)
    print(f"Действующие подписки на {today:%d.%m.%Y} · платные {paid}, пробные {trial}.", flush=True)
    if not args.apply:
        return 0
    try:
        return asyncio.run(migrate(path, today))
    except Exception as exc:
        logger.error("Перенос остановлен: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
