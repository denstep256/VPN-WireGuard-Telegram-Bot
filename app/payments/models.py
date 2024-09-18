from sqlalchemy import create_engine, Column, Integer, String, DateTime, Enum, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import enum
import config

# Создайте соединение с базой данных
DATABASE_URL = config.DB_URL_KEYS
engine = create_engine(DATABASE_URL, echo=True)

# Создайте базовый класс для моделей
Base = declarative_base()

class SubscriptionDuration(enum.Enum):
    MONTHLY = 'monthly'
    SEMI_ANNUAL = 'semi_annual'
    ANNUAL = 'annual'

class IssuedKey(Base):
    __tablename__ = 'issued_keys'
    user_id = Column(Integer, primary_key=True)
    file_name = Column(String, nullable=False)
    expiry_date = Column(DateTime, nullable=False)
    duration = Column(Enum(SubscriptionDuration), nullable=False)
    is_used = Column(Boolean, default=True)  # Помечает файл как используемый

# Создайте таблицы
Base.metadata.create_all(engine)

# Создайте фабрику сессий
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

