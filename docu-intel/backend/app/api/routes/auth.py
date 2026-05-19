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
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    token = create_access_token(str(user.id))
    secure_cookie = settings.environment == "production" if settings.auth_cookie_secure is None else settings.auth_cookie_secure
    response.set_cookie(
        settings.auth_cookie_name,
        token,
        httponly=True,
        samesite=settings.auth_cookie_samesite,
        secure=secure_cookie,
        max_age=settings.jwt_expire_minutes * 60,
    )
    return LoginResponse(access_token=token, user=UserRead.model_validate(user))


@router.get("/me", response_model=UserRead)
def me(user: User = Depends(get_current_user)) -> User:
    return user
