import os

from sqlalchemy.orm import Session
from datetime import datetime, timedelta

from app.payments.models import SessionLocal, SubscriptionDuration, IssuedKey
from app.payments.common import FILES_DIR
from app.addons.utilits import calculate_expiry_date


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def issue_file(db: Session, user_id: int, file_name: str, duration: SubscriptionDuration):
    expiry_date = datetime.now() + {
        SubscriptionDuration.MONTHLY: timedelta(days=30),
        SubscriptionDuration.SEMI_ANNUAL: timedelta(days=180),
        SubscriptionDuration.ANNUAL: timedelta(days=365)
    }[duration]
    db.add(IssuedKey(user_id=user_id, file_name=file_name, expiry_date=expiry_date, duration=duration))
    db.commit()


def mark_file_as_unused(db: Session, user_id: int):
    db.query(IssuedKey).filter(IssuedKey.user_id == user_id).update({'is_used': False})
    db.commit()


def renew_subscription(db, user_id, duration):
    current_subscription = db.query(IssuedKey).filter(IssuedKey.user_id == user_id).first()

    if current_subscription:
        new_expiry_date = calculate_expiry_date(current_subscription.expiry_date, duration)
        db.query(IssuedKey).filter(IssuedKey.user_id == user_id).update({
            IssuedKey.expiry_date: new_expiry_date,
            IssuedKey.is_used: True  # Убедитесь, что это поле обновляется правильно
        })
        db.commit()


def get_available_files(db: Session):
    # Получаем все файлы, которые были выданы и отмечены как использованные
    issued_files = {row.file_name for row in db.query(IssuedKey).filter(IssuedKey.is_used == True).all()}

    # Получаем все файлы из директории, исключая .DS_Store
    all_files = {f for f in os.listdir(FILES_DIR) if not f.startswith('.')}

    # Возвращаем файлы, которые не были выданы
    available_files = all_files - issued_files

    return available_files