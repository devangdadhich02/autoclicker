from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, DbSession
from app.api.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    RefreshRequest,
    TokenResponse,
)
from app.api.schemas.user import UserResponse
from app.core.exceptions import AuthenticationError
from app.core.security import create_access_token, create_refresh_token, decode_token
from app.services.user_service import UserService

router = APIRouter()


@router.post("/token", response_model=TokenResponse, summary="OAuth2 password login")
async def login_form(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: DbSession,
) -> TokenResponse:
    svc = UserService(db)
    try:
        user = await svc.authenticate(form_data.username, form_data.password)
    except AuthenticationError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=exc.message)
    return TokenResponse(
        access_token=create_access_token(user.id, {"role": user.role}),
        refresh_token=create_refresh_token(user.id),
    )


@router.post("/login", response_model=TokenResponse, summary="JSON login")
async def login_json(body: LoginRequest, db: DbSession) -> TokenResponse:
    svc = UserService(db)
    try:
        user = await svc.authenticate(body.email, body.password)
    except AuthenticationError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=exc.message)
    return TokenResponse(
        access_token=create_access_token(user.id, {"role": user.role}),
        refresh_token=create_refresh_token(user.id),
    )


@router.post("/refresh", response_model=TokenResponse, summary="Refresh access token")
async def refresh_token(body: RefreshRequest, db: DbSession) -> TokenResponse:
    try:
        payload = decode_token(body.refresh_token)
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type.")
        user_id: str = payload["sub"]
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token.")

    svc = UserService(db)
    try:
        user = await svc.get_by_id(user_id)
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found.")

    return TokenResponse(
        access_token=create_access_token(user.id, {"role": user.role}),
        refresh_token=create_refresh_token(user.id),
    )


@router.get("/me", response_model=UserResponse, summary="Current user profile")
async def get_me(current_user: CurrentUser) -> UserResponse:
    return UserResponse.model_validate(current_user)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: ChangePasswordRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> None:
    svc = UserService(db)
    try:
        await svc.authenticate(current_user.email, body.current_password)
    except AuthenticationError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password incorrect.")
    await svc.update_password(current_user.id, body.new_password)
