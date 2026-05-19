"""Crear usuario admin inicial.
Uso: python scripts/create_admin.py

Lee ADMIN_EMAIL, ADMIN_PASSWORD, ADMIN_NAME de .env.production
o acepta argumentos de linea de comandos.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Añadir backend al path para poder importar
BACKEND = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from app.database.session import SessionLocal
from app.models import User
from app.core.security import hash_password


def main():
    # Cargar desde .env si existe
    env_file = Path(__file__).parent.parent / ".env.production"
    env_vars = {}
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                key, _, value = line.partition("=")
                env_vars[key.strip()] = value.strip().strip('"').strip("'")

    email = os.environ.get("ADMIN_EMAIL") or env_vars.get("ADMIN_EMAIL") or "admin@docuintel.local"
    password = os.environ.get("ADMIN_PASSWORD") or env_vars.get("ADMIN_PASSWORD") or ""
    name = os.environ.get("ADMIN_NAME") or env_vars.get("ADMIN_NAME") or "Administrador"

    if len(sys.argv) > 1:
        email = sys.argv[1]
    if len(sys.argv) > 2:
        password = sys.argv[2]
    if len(sys.argv) > 3:
        name = sys.argv[3]

    if not password:
        print("ERROR: se necesita password. Pasalo como argumento o define ADMIN_PASSWORD en .env.production")
        sys.exit(1)

    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == email).first()
        if existing:
            print(f"Usuario '{email}' ya existe — no se ha modificado.")
            return

        user = User(
            email=email,
            name=name,
            password_hash=hash_password(password),
            role="admin",
        )
        db.add(user)
        db.commit()
        print(f"Admin creado: {email}")
    except Exception as exc:
        db.rollback()
        print(f"ERROR: {exc}")
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()