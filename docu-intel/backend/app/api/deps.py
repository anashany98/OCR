from __future__ import annotations

import logging

from fastapi import Cookie, Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import decode_access_token
from app.database.session import get_db
from app.models import User

logger = logging.getLogger(__name__)


def get_current_user(
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
    cookie_token: str | None = Cookie(default=None, alias=settings.auth_cookie_name),
    token: str | None = Query(default=None),
) -> User:
    # ``token`` is supplied via the ``?token=...`` query string. The
    # ``EventSource`` browser API cannot send custom ``Authorization``
    # headers so SSE endpoints accept the bearer token this way.
    query_token = token
    bearer = None
    if cookie_token:
        bearer = cookie_token
    if authorization and authorization.lower().startswith("bearer "):
        bearer = authorization.split(" ", 1)[1].strip()
    if not bearer and query_token:
        bearer = query_token
    if not bearer:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    token = bearer

    try:
        payload = decode_access_token(token)
        user_id = int(payload["sub"])
    except Exception as exc:
        logger.warning("auth_token_invalid error=%s", str(exc))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        ) from None

    user = db.get(User, user_id)
    if not user or not user.is_active:
        logger.warning(
            "auth_user_not_found user_id=%s active=%s", user_id, user.is_active if user else False
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Inactive user")
    return user


def require_roles(*roles: str):
    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
            )
        return user

    return dependency
