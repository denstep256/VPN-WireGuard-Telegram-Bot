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
    tg_id = mapped_column(BigInteger, unique=True)
    username: Mapped[str] = mapped_column(String(25), nullable=True)
    first_name: Mapped[str] = mapped_column(String(25), nullable=True)
    date: Mapped[str] = mapped_column(String(25))

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
    notif_oneday = mapped_column(Boolean, default=False)
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
    notif_oneday = mapped_column(Boolean, default=False)

class Server(Base):
    __tablename__ = 'servers'

    id: Mapped[int] = mapped_column(primary_key=True)
    region = mapped_column(String(25))
    region_id: Mapped[int] = mapped_column()
    host_ip = mapped_column(String(25))
    port = mapped_column(String(25))
    password = mapped_column(String(25))
    date = mapped_column(String(25))
    is_active = mapped_column(Boolean, default=True)

async def async_main():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


