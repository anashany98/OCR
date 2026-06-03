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
        logger.warning("auth_login_failed email=%s", payload.email)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    logger.info("auth_login_success user_id=%s email=%s", user.id, user.email)
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
