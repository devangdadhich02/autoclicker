from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.user import UserRole
from app.services.user_service import UserService

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

_test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
_test_session_factory = async_sessionmaker(_test_engine, expire_on_commit=False)


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="function")
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with _test_session_factory() as session:
        yield session

    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture(scope="function")
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def admin_user(db_session: AsyncSession) -> Any:
    svc = UserService(db_session)
    user = await svc.create(
        email="admin@test.com",
        full_name="Test Admin",
        password="TestPassword1!",
        role=UserRole.admin,
    )
    await db_session.commit()
    return user


@pytest_asyncio.fixture
async def operator_user(db_session: AsyncSession) -> Any:
    svc = UserService(db_session)
    user = await svc.create(
        email="operator@test.com",
        full_name="Test Operator",
        password="TestPassword1!",
        role=UserRole.operator,
    )
    await db_session.commit()
    return user


@pytest_asyncio.fixture
async def admin_token(client: AsyncClient, admin_user: Any) -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@test.com", "password": "TestPassword1!"},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


@pytest_asyncio.fixture
async def operator_token(client: AsyncClient, operator_user: Any) -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "operator@test.com", "password": "TestPassword1!"},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]
