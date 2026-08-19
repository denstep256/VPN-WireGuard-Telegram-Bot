from datetime import datetime
import logging

from sqlalchemy import BigInteger, String, Boolean, UniqueConstraint, DateTime, Integer, ForeignKey, inspect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.ext.asyncio import AsyncAttrs, async_sessionmaker, create_async_engine

import config
from app.paths import resolve_database_url
from app.time_utils import utc_now_naive

logger = logging.getLogger(__name__)

engine = create_async_engine(url=resolve_database_url(config.DB_URL_USERS))


async_session = async_sessionmaker(engine, expire_on_commit=False)

class Base(AsyncAttrs, DeclarativeBase):
    pass

class User(Base):
    __tablename__ = 'users'

    id: Mapped[int] = mapped_column(primary_key=True)
    tg_id = mapped_column(BigInteger, unique=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    bonus_balance: Mapped[int] = mapped_column(Integer, default=0)
    date: Mapped[str] = mapped_column(String(25))


class Payments(Base):
    __tablename__ = 'payments'
    __table_args__ = (
        UniqueConstraint("provider_payment_charge_id", name="uq_payment_provider_charge"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tg_id = mapped_column(BigInteger)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    price: Mapped[int] = mapped_column()
    date: Mapped[str] = mapped_column(String(25))
    tarific_plan: Mapped[str] = mapped_column(String(25))
    provider_payment_charge_id: Mapped[str] = mapped_column(String(128))

class Subscribers(Base):
    __tablename__ = 'subscribers'

    id: Mapped[int] = mapped_column(primary_key=True)
    tg_id = mapped_column(BigInteger)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    file_name: Mapped[str] = mapped_column(String(128))
    subscription: Mapped[str] = mapped_column(String(32))
    expiry_date: Mapped[str] = mapped_column(String(10))
    server_region: Mapped[str] = mapped_column(String(25))
    server_region_id: Mapped[int] = mapped_column()
    notif_oneday = mapped_column(Boolean, default=False)
    #note нужно для ручного добавления подписки
    note: Mapped[str | None] = mapped_column(String, nullable=True, default="")

class TestPeriod(Base):
    __tablename__ = 'test_period'
    __table_args__ = (UniqueConstraint("tg_id", name="uq_test_period_tg_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tg_id = mapped_column(BigInteger)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    file_name: Mapped[str] = mapped_column(String(128))
    subscription: Mapped[str] = mapped_column(String(32))
    expiry_date: Mapped[str] = mapped_column(String(10))
    notif_oneday = mapped_column(Boolean, default=False)
    server_region: Mapped[str | None] = mapped_column(String(25), nullable=True)
    server_region_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

class Server(Base):
    __tablename__ = 'servers'
    __table_args__ = (
        UniqueConstraint("region", "region_id", name="uq_server_region_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    region = mapped_column(String(25))
    region_id: Mapped[int] = mapped_column()
    host_ip = mapped_column(String(255))
    port = mapped_column(String(5))
    password = mapped_column(String(256))
    date = mapped_column(String(25))
    is_active = mapped_column(Boolean, default=True)

class Referral(Base):
    __tablename__ = "referrals"
    __table_args__ = (
        UniqueConstraint("user_tg_id", name="uq_ref_user"),
        UniqueConstraint("ref_code", name="uq_ref_code"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    user_tg_id: Mapped[int] = mapped_column(BigInteger, index=True)  # владелец кода
    ref_code: Mapped[str] = mapped_column(String(16), index=True)
    invited_by_tg_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    # чтобы 100₽ начислялись 1 раз после первой оплаты реферала
    inviter_rewarded: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)


class PromoCode(Base):
    __tablename__ = "promo_codes"
    __table_args__ = (UniqueConstraint("code", name="uq_promo_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)

    code: Mapped[str] = mapped_column(String(32), index=True)
    discount_percent: Mapped[int] = mapped_column(Integer, default=10)

    # None => промокод общий (для всех), иначе персональный
    owner_tg_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)

    # на будущее (админка):
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    first_purchase_only: Mapped[bool] = mapped_column(Boolean, default=True)
    max_uses_per_user: Mapped[int] = mapped_column(Integer, default=1)  # 1 = одноразовый
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)

class PromoRedemption(Base):
    __tablename__ = "promo_redemptions"
    __table_args__ = (
        UniqueConstraint("user_tg_id", "promo_id", name="uq_user_promo_once"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_tg_id: Mapped[int] = mapped_column(BigInteger, index=True)
    promo_id: Mapped[int] = mapped_column(ForeignKey("promo_codes.id"), index=True)

    is_activated: Mapped[bool] = mapped_column(Boolean, default=True)
    uses_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

def _apply_sqlite_compatibility_migrations(sync_conn) -> None:
    """Bring databases created by older revisions to the current lightweight schema."""
    if sync_conn.dialect.name != "sqlite":
        return

    test_period_columns = {
        row[1]
        for row in sync_conn.exec_driver_sql("PRAGMA table_info(test_period)").fetchall()
    }
    if "server_region" not in test_period_columns:
        sync_conn.exec_driver_sql(
            "ALTER TABLE test_period ADD COLUMN server_region VARCHAR(25)"
        )
    if "server_region_id" not in test_period_columns:
        sync_conn.exec_driver_sql(
            "ALTER TABLE test_period ADD COLUMN server_region_id INTEGER"
        )

    unique_indexes = (
        (
            "uq_payment_provider_charge_idx",
            "payments",
            "provider_payment_charge_id",
            "provider_payment_charge_id IS NOT NULL AND provider_payment_charge_id != ''",
        ),
        ("uq_test_period_tg_id_idx", "test_period", "tg_id", "tg_id IS NOT NULL"),
        (
            "uq_server_region_id_idx",
            "servers",
            "region, region_id",
            "region IS NOT NULL AND region_id IS NOT NULL",
        ),
    )
    for index_name, table_name, columns, predicate in unique_indexes:
        duplicate_count = sync_conn.exec_driver_sql(
            f"SELECT COUNT(*) FROM ("
            f"SELECT {columns} FROM {table_name} WHERE {predicate} "
            f"GROUP BY {columns} HAVING COUNT(*) > 1"
            f")"
        ).scalar_one()
        if duplicate_count:
            raise RuntimeError(
                f"Cannot create unique index {index_name}: "
                f"{duplicate_count} duplicate groups found in {table_name}."
            )
        sync_conn.exec_driver_sql(
            f"CREATE UNIQUE INDEX IF NOT EXISTS {index_name} "
            f"ON {table_name} ({columns})"
        )


async def async_main():
    try:
        logger.info("Database initialization started: create_all for declared models.")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.run_sync(_apply_sqlite_compatibility_migrations)
            table_names = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())
        logger.info(
            "Database initialization completed: %s tables ensured (%s).",
            len(table_names),
            ", ".join(sorted(table_names)),
        )
    except Exception:
        logger.exception("Database initialization failed while creating tables.")
        raise
