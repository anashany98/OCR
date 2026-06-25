import hashlib
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.security import create_access_token, verify_password
from app.database.session import get_db
from app.models import User
from app.schemas.auth import LoginRequest, LoginResponse, UserRead

router = APIRouter()

logger = logging.getLogger(__name__)


def _redact_email(email: str) -> str:
    """Return a short, non-reversible identifier for a user-provided
    email. L-6: full email in a log file is PII and ends up in
    Sentry breadcrumbs unless ``SENTRY_SEND_PII=false`` is honored by
    the host. A short hash lets the operator correlate repeated
    failures without exposing the address.
    """
    digest = hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()[:10]
    return f"id_{digest}"


@router.post("/login", response_model=LoginResponse)
@limiter.limit(settings.auth_login_rate_limit)
def login(
    request: Request,
    payload: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> LoginResponse:
    user = db.scalar(select(User).where(User.email == payload.email))
    if not user or not user.is_active or not verify_password(payload.password, user.password_hash):
        # L-6: log a non-reversible identifier, not the email itself.
        logger.warning("auth_login_failed user=%s", _redact_email(payload.email))
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    # L-6: log user id but not the email (PII).
    logger.info("auth_login_success user_id=%s", user.id)
    token = create_access_token(str(user.id))
    secure_cookie = settings.environment == "production" or settings.auth_cookie_secure is True
    response.set_cookie(
        settings.auth_cookie_name,
        token,
        httponly=True,
        samesite=settings.auth_cookie_samesite,
        secure=secure_cookie,
        max_age=settings.jwt_expire_minutes * 60,
    )
    return LoginResponse(access_token=token, user=UserRead.model_validate(user))


@router.post("/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(
        settings.auth_cookie_name,
        httponly=True,
        samesite=settings.auth_cookie_samesite,
        secure=settings.environment == "production" or settings.auth_cookie_secure is True,
    )
    return {"message": "Logged out successfully"}


@router.get("/me", response_model=UserRead)
def me(user: User = Depends(get_current_user)) -> User:
    return user
