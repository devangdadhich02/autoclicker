from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.api.deps import AdminUser, DbSession
from app.api.schemas.user import UserCreate, UserResponse, UserUpdate
from app.core.exceptions import ConflictError, NotFoundError
from app.services.user_service import UserService

router = APIRouter()


@router.get("", response_model=list[UserResponse])
async def list_users(
    db: DbSession,
    _admin: AdminUser,
    skip: int = 0,
    limit: int = 50,
) -> list[UserResponse]:
    svc = UserService(db)
    users = await svc.list_users(skip=skip, limit=limit)
    return [UserResponse.model_validate(u) for u in users]


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(body: UserCreate, db: DbSession, _admin: AdminUser) -> UserResponse:
    svc = UserService(db)
    try:
        user = await svc.create(
            email=body.email,
            full_name=body.full_name,
            password=body.password,
            role=body.role,
        )
    except ConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.message)
    return UserResponse.model_validate(user)


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(user_id: str, db: DbSession, _admin: AdminUser) -> UserResponse:
    svc = UserService(db)
    try:
        user = await svc.get_by_id(user_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message)
    return UserResponse.model_validate(user)


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str, body: UserUpdate, db: DbSession, _admin: AdminUser
) -> UserResponse:
    svc = UserService(db)
    try:
        user = await svc.get_by_id(user_id)
        updates = body.model_dump(exclude_unset=True)
        for key, value in updates.items():
            setattr(user, key, value)
        await db.flush()
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message)
    return UserResponse.model_validate(user)
