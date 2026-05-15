from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password
from app.models import User
from app.services.integration_init import create_initial_integration_data


def create_initial_admin(db: Session) -> User:
    existing = db.scalar(select(User).where(User.email == settings.admin_email))
    if existing:
        create_initial_integration_data(db)
        return existing

    admin = User(
        email=settings.admin_email,
        name=settings.admin_name,
        password_hash=hash_password(settings.admin_password),
        role="admin",
        is_active=True,
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    create_initial_integration_data(db)
    return admin
