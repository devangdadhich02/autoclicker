from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthenticationError, ConflictError, NotFoundError
from app.core.security import hash_password, verify_password
from app.models.user import User, UserRole


class UserService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_by_id(self, user_id: str) -> User:
        result = await self._db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user is None:
            raise NotFoundError("User", user_id)
        return user

    async def get_by_email(self, email: str) -> User | None:
        result = await self._db.execute(select(User).where(User.email == email.lower()))
        return result.scalar_one_or_none()

    async def create(
        self,
        email: str,
        full_name: str,
        password: str,
        role: UserRole = UserRole.operator,
    ) -> User:
        existing = await self.get_by_email(email)
        if existing is not None:
            raise ConflictError(f"A user with email '{email}' already exists.")

        user = User(
            email=email.lower(),
            full_name=full_name,
            hashed_password=hash_password(password),
            role=role,
            is_active=True,
            is_verified=True,
        )
        self._db.add(user)
        await self._db.flush()
        return user

    async def authenticate(self, email: str, password: str) -> User:
        user = await self.get_by_email(email)
        if user is None or not verify_password(password, user.hashed_password):
            raise AuthenticationError()
        if not user.is_active:
            raise AuthenticationError("Account is disabled.")
        return user

    async def update_password(self, user_id: str, new_password: str) -> None:
        user = await self.get_by_id(user_id)
        user.hashed_password = hash_password(new_password)
        await self._db.flush()

    async def list_users(self, skip: int = 0, limit: int = 50) -> list[User]:
        result = await self._db.execute(select(User).offset(skip).limit(limit))
        return list(result.scalars().all())

    async def set_active(self, user_id: str, active: bool) -> User:
        user = await self.get_by_id(user_id)
        user.is_active = active
        await self._db.flush()
        return user
