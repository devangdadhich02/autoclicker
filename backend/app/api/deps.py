from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import credentials_exception, forbidden_exception
from app.core.security import decode_token
from app.db.session import get_db
from app.models.user import User, UserRole
from app.services.user_service import UserService

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise credentials_exception
        user_id: str | None = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    svc = UserService(db)
    try:
        user = await svc.get_by_id(user_id)
    except Exception:
        raise credentials_exception

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled.")

    return user


async def get_current_admin(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    if current_user.role != UserRole.admin:
        raise forbidden_exception
    return current_user


async def get_current_operator_or_admin(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    if current_user.role not in (UserRole.admin, UserRole.operator):
        raise forbidden_exception
    return current_user


CurrentUser = Annotated[User, Depends(get_current_user)]
AdminUser = Annotated[User, Depends(get_current_admin)]
OperatorUser = Annotated[User, Depends(get_current_operator_or_admin)]
DbSession = Annotated[AsyncSession, Depends(get_db)]
