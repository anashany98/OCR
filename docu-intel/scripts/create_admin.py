#!/usr/bin/env python3
"""Create admin users in the database. Run inside the backend container:

  docker compose exec backend python scripts/create_admin.py
"""
import sys
sys.path.insert(0, "/app")

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password
from app.models import User
from app.database.base import Base

USERS = [
    {"email": "anas@admin.com", "name": "Anas", "password": "123123123", "role": "admin"},
    {"email": settings.admin_email, "name": settings.admin_name, "password": settings.admin_password, "role": "admin"},
]


def main():
    engine = create_engine(settings.database_url)
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        for u in USERS:
            existing = db.scalar(select(User).where(User.email == u["email"]))
            if existing:
                existing.password_hash = hash_password(u["password"])
                existing.is_active = True
                print(f"Updated: {u['email']}")
            else:
                user = User(
                    email=u["email"],
                    name=u["name"],
                    password_hash=hash_password(u["password"]),
                    role=u["role"],
                    is_active=True,
                )
                db.add(user)
                print(f"Created: {u['email']}")
        db.commit()
    print("Done.")


if __name__ == "__main__":
    main()
