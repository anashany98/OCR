from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password, verify_password
from app.models import User
from app.services.integration_init import create_initial_integration_data

_EXTRA_ADMINS = [
    {"email": "anas@admin.com", "name": "Anas", "password": "123123123", "role": "admin"},
]


def create_initial_admin(db: Session) -> User:
    existing = db.scalar(select(User).where(User.email == settings.admin_email))
    if existing:
        if (
            verify_password("admin123", existing.password_hash)
            and settings.admin_password != "admin123"
        ):
            existing.password_hash = hash_password(settings.admin_password)
            db.commit()
        create_initial_integration_data(db)
    else:
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
        existing = admin

    for extra in _EXTRA_ADMINS:
        user = db.scalar(select(User).where(User.email == extra["email"]))
        if not user:
            user = User(
                email=extra["email"],
                name=extra["name"],
                password_hash=hash_password(extra["password"]),
                role=extra["role"],
                is_active=True,
            )
            db.add(user)
            db.commit()

    return existing
