import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password, verify_password
from app.models import User
from app.services.integration_init import create_initial_integration_data

logger = logging.getLogger("app.database.init_db")

# Legacy fixed-account emails removed in F0-01.
# The only admin created at boot is the one configured via ADMIN_EMAIL / ADMIN_PASSWORD.


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

    return existing


# ---------------------------------------------------------------------------
# F0-01: disable legacy bootstrap admin accounts
# ---------------------------------------------------------------------------

# Known legacy emails that were hardcoded in earlier versions.
LEGACY_BOOTSTRAP_EMAILS: frozenset[str] = frozenset({"anas@admin.com"})


def disable_legacy_bootstrap_admin(
    db: Session,
    *,
    dry_run: bool = True,
    actor_id: int | None = None,
) -> list[dict[str, Any]]:
    """Deactivate legacy fixed-admin accounts.

    Parameters
    ----------
    dry_run:
        When True (default) no writes occur; returns what *would* happen.
    actor_id:
        User id recorded in the audit log.  May be ``None`` for system actions.

    Returns
    -------
    List of dicts describing the action taken (or proposed) for each legacy account.
    """
    from app.models.audit import AuditLog  # avoid circular import at module level

    results: list[dict[str, Any]] = []

    for email in LEGACY_BOOTSTRAP_EMAILS:
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            results.append({"email": email, "action": "not_found"})
            continue

        if not user.is_active:
            results.append({"email": email, "action": "already_inactive"})
            continue

        if dry_run:
            results.append(
                {
                    "email": email,
                    "user_id": user.id,
                    "action": "would_deactivate",
                }
            )
        else:
            user.is_active = False
            db.add(
                AuditLog(
                    user_id=actor_id,
                    action="disable_legacy_bootstrap_admin",
                    entity_type="user",
                    entity_id=user.id,
                    details_json={"email": email, "reason": "legacy fixed-account removal"},
                )
            )
            db.commit()
            results.append({"email": email, "user_id": user.id, "action": "deactivated"})

    return results
