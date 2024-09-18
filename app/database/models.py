from sqlalchemy import BigInteger, String, Boolean
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.ext.asyncio import AsyncAttrs, async_sessionmaker, create_async_engine

import config

engine = create_async_engine(url=config.DB_URL_USERS)


async_session = async_sessionmaker(engine)

class Base(AsyncAttrs, DeclarativeBase):
    pass

class User(Base):
    __tablename__ = 'users'

    id: Mapped[int] = mapped_column(primary_key=True)
    tg_id = mapped_column(BigInteger)
    username: Mapped[str] = mapped_column(String(25))
    first_name: Mapped[str] = mapped_column(String(25))
    test_period = mapped_column(Boolean, default=False)
    date_add: Mapped[str] = mapped_column(String(25))

class Payments(Base):
    __tablename__ = 'payments'

    id: Mapped[int] = mapped_column(primary_key=True)
    tg_id = mapped_column(BigInteger)
    amount: Mapped[int] = mapped_column()
    time_to_add: Mapped[str] = mapped_column(String(25))
    payload: Mapped[str] = mapped_column(String(25))

class Static(Base):
    __tablename__ = 'static'

    id: Mapped[int] = mapped_column(primary_key=True)
    tg_id = mapped_column(BigInteger)
    username: Mapped[str] = mapped_column(String(25))

class Subscribers(Base):
    __tablename__ = 'subscribers'

    id: Mapped[int] = mapped_column(primary_key=True)
    tg_id = mapped_column(BigInteger)
    username: Mapped[str] = mapped_column(String(25))
    file_name: Mapped[str] = mapped_column(String(25))
    subscription: Mapped[str] = mapped_column(String(25))
    expiry_date: Mapped[str] = mapped_column(String(25))
    notif_oneday = mapped_column(Boolean, default=False)
    note: Mapped[str | None] = mapped_column(String, nullable=True, default="")
    subscripti: Mapped[str] = mapped_column(String(25))

class TestPeriod(Base):
    __tablename__ = 'test_period'

    id: Mapped[int] = mapped_column(primary_key=True)
    tg_id = mapped_column(BigInteger)
    username: Mapped[str] = mapped_column(String(25))
    file_name: Mapped[str] = mapped_column(String(25))
    subscription: Mapped[str] = mapped_column(String(25))
    expiry_date: Mapped[str] = mapped_column(String(25))
    notif_oneday = mapped_column(Boolean, default=False)


async def async_main():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


