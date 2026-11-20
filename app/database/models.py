from datetime import datetime
import logging
from zoneinfo import ZoneInfo

from sqlalchemy import BigInteger, case, String, Boolean, UniqueConstraint, DateTime, Integer, ForeignKey, func, inspect, select, text, update
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.ext.asyncio import AsyncAttrs, async_sessionmaker, create_async_engine

import config

logger = logging.getLogger(__name__)

engine = create_async_engine(url=config.DB_URL_USERS, connect_args={"timeout": 45})


async_session = async_sessionmaker(engine, expire_on_commit=False)

class Base(AsyncAttrs, DeclarativeBase):
    pass

class User(Base):
    __tablename__ = 'users'

    id: Mapped[int] = mapped_column(primary_key=True)
    tg_id = mapped_column(BigInteger, unique=True)
    username: Mapped[str] = mapped_column(String(25), nullable=True)
    first_name: Mapped[str] = mapped_column(String(25), nullable=True)
    bonus_balance: Mapped[int] = mapped_column(Integer, default=0)
    date: Mapped[str] = mapped_column(String(25))
    protocol: Mapped[str | None] = mapped_column(String(25), nullable=True)


class Payments(Base):
    __tablename__ = 'payments'

    id: Mapped[int] = mapped_column(primary_key=True)
    tg_id = mapped_column(BigInteger)
    username: Mapped[str] = mapped_column(String(25), nullable=True)
    price: Mapped[int] = mapped_column()
    date: Mapped[str] = mapped_column(String(25))
    tarific_plan: Mapped[str] = mapped_column(String(25))
    provider_payment_charge_id: Mapped[str] = mapped_column(String(25))

class Subscribers(Base):
    __tablename__ = 'subscribers'

    id: Mapped[int] = mapped_column(primary_key=True)
    tg_id = mapped_column(BigInteger)
    username: Mapped[str] = mapped_column(String(25), nullable=True)
    file_name: Mapped[str] = mapped_column(String(25))
    subscription: Mapped[str] = mapped_column(String(25))
    expiry_date: Mapped[str] = mapped_column(String(25))
    server_region: Mapped[str] = mapped_column(String(25))
    server_region_id: Mapped[int] = mapped_column()
    protocol: Mapped[str] = mapped_column(String(25), default="wireguard", server_default="wireguard")
    xui_sub_id: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)
    notif_oneday = mapped_column(Boolean, default=False)
    purchase_charge_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provisioned: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("1"))
    #note нужно для ручного добавления подписки
    note: Mapped[str | None] = mapped_column(String, nullable=True, default="")

class TestPeriod(Base):
    __tablename__ = 'test_period'

    id: Mapped[int] = mapped_column(primary_key=True)
    tg_id = mapped_column(BigInteger)
    username: Mapped[str] = mapped_column(String(25), nullable=True)
    file_name: Mapped[str] = mapped_column(String(25))
    subscription: Mapped[str] = mapped_column(String(25))
    expiry_date: Mapped[str] = mapped_column(String(25))
    server_region: Mapped[str | None] = mapped_column(String(25), nullable=True, default=None)
    server_region_id: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    protocol: Mapped[str] = mapped_column(String(25), default="wireguard", server_default="wireguard")
    xui_sub_id: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)
    notif_oneday = mapped_column(Boolean, default=False)

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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


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

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

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

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


async def _ensure_column(conn, table_name: str, column_name: str, ddl: str) -> None:
    columns = await conn.run_sync(
        lambda sync_conn: {col["name"] for col in inspect(sync_conn).get_columns(table_name)}
    )
    if column_name in columns:
        return

    await conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {ddl}"))
    logger.info("Database migration applied: %s.%s added.", table_name, column_name)


async def _run_lightweight_migrations(conn) -> None:
    await _ensure_column(conn, "subscribers", "protocol", "protocol VARCHAR(25) DEFAULT 'wireguard'")
    await _ensure_column(conn, "subscribers", "xui_sub_id", "xui_sub_id VARCHAR(64)")
    await _ensure_column(conn, "test_period", "protocol", "protocol VARCHAR(25) DEFAULT 'wireguard'")
    await _ensure_column(conn, "test_period", "xui_sub_id", "xui_sub_id VARCHAR(64)")
    await _ensure_column(conn, "test_period", "server_region", "server_region VARCHAR(25)")
    await _ensure_column(conn, "test_period", "server_region_id", "server_region_id INTEGER")
    await _ensure_column(conn, "users", "protocol", "protocol VARCHAR(25)")
    await _ensure_column(conn, "subscribers", "purchase_charge_id", "purchase_charge_id VARCHAR(255)")
    await _ensure_column(conn, "subscribers", "provisioned", "provisioned BOOLEAN NOT NULL DEFAULT 1")


async def refresh_user_protocol(session, tg_id: int | None = None) -> None:
    today = datetime.now(ZoneInfo(config.VPN_TIMEZONE)).date().isoformat()
    paid = select(Subscribers.protocol).where(
        Subscribers.tg_id == User.tg_id, Subscribers.provisioned.is_(True),
        func.date(Subscribers.expiry_date) >= today,
    ).correlate(User)
    trial = select(TestPeriod.protocol).where(
        TestPeriod.tg_id == User.tg_id, TestPeriod.subscription == "trial",
        func.date(TestPeriod.expiry_date) >= today,
    ).correlate(User)
    wireguard = paid.where(Subscribers.protocol.in_(("wireguard", "both"))).exists() | trial.where(
        TestPeriod.protocol.in_(("wireguard", "both"))
    ).exists()
    xui = paid.where(Subscribers.protocol.in_(("xui", "both"))).exists() | trial.where(
        TestPeriod.protocol.in_(("xui", "both"))
    ).exists()
    statement = update(User).values(protocol=case(
        (wireguard & xui, "both"), (wireguard, "wireguard"), (xui, "xui"), else_=None,
    ))
    if tg_id is not None:
        statement = statement.where(User.tg_id == tg_id)
    await session.execute(statement.execution_options(synchronize_session=False))


async def async_main():
    try:
        logger.info("Database initialization started: create_all for declared models.")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await _run_lightweight_migrations(conn)
            table_names = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())
        async with async_session.begin() as session:
            await refresh_user_protocol(session)
        logger.info(
            "Database initialization completed: %s tables ensured (%s).",
            len(table_names),
            ", ".join(sorted(table_names)),
        )
    except Exception:
        logger.exception("Database initialization failed while creating tables.")
        raise
