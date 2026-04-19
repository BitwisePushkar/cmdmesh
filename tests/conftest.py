from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
import fakeredis.aioredis as fakeredis
from backend.config import Settings, get_settings
from backend.db.base import Base
from backend.dependencies.db import get_db
from backend.dependencies.redis import get_redis
from backend.main import create_app
from backend.models.user import User
from backend.models.token import RefreshToken
from backend.services.auth_service import AuthService
from backend.schemas.auth import SignupRequest

@pytest.fixture(scope="session")
def test_settings() -> Settings:
    key = Fernet.generate_key().decode()
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        redis_url="redis://localhost:6379/15",
        jwt_secret_key="test-secret-key-not-for-production",
        jwt_algorithm="HS256",
        access_token_expire_minutes=15,
        refresh_token_expire_days=7,
        token_encryption_key=key,
        smtp_host="localhost",
        smtp_port=1025,
        smtp_from="test@cmdmesh.dev",
        smtp_tls=False,
        smtp_starttls=False,
        otp_ttl_seconds=300,
        otp_max_attempts=5,
        otp_resend_cooldown_seconds=10,
        password_reset_otp_ttl_seconds=300,
        password_reset_otp_max_attempts=5,
        password_reset_otp_cooldown_seconds=10,
        app_env="testing",
    )

@pytest_asyncio.fixture(scope="session")
async def engine(test_settings):
    eng = create_async_engine(
        test_settings.database_url,
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    yield eng
    await eng.dispose()

@pytest_asyncio.fixture
async def db_session(engine) -> AsyncGenerator[AsyncSession, None]:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with factory() as session:
        yield session
        await session.rollback()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

@pytest_asyncio.fixture
async def redis_client():
    client = fakeredis.FakeRedis(decode_responses=True)
    yield client
    await client.flushall()
    await client.aclose()

@pytest.fixture
def mock_smtp():
    with patch("backend.services.email_service.aiosmtplib.send", new_callable=AsyncMock) as m:
        yield m

@pytest.fixture
def mock_celery():
    otp_mock = MagicMock()
    reset_mock = MagicMock()

    with (
        patch(
            "backend.tasks.email_tasks.send_otp_email.delay",
            otp_mock,
        ),
        patch(
            "backend.tasks.email_tasks.send_password_reset_email.delay",
            reset_mock,
        ),
    ):
        yield {"otp": otp_mock, "reset": reset_mock}

@pytest_asyncio.fixture
async def app(test_settings, db_session, redis_client, mock_smtp, mock_celery) -> FastAPI:
    get_settings.cache_clear()
    application = create_app()
    application.dependency_overrides[get_settings] = lambda: test_settings
    async def override_db():
        yield db_session
    async def override_redis():
        yield redis_client
    application.dependency_overrides[get_db] = override_db
    application.dependency_overrides[get_redis] = override_redis
    yield application
    application.dependency_overrides.clear()
    get_settings.cache_clear()

@pytest_asyncio.fixture
async def client(app) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

@pytest_asyncio.fixture
async def verified_user(db_session) -> User:
    data = SignupRequest(
        username="testuser",
        email="test@example.com",
        password="Password1",
    )
    user = await AuthService.create_verified_user(db_session, data)
    await db_session.commit()
    return user

@pytest_asyncio.fixture
async def auth_tokens(client, verified_user) -> dict[str, Any]:
    r = await client.post("/auth/login", json={
        "identifier": "testuser",
        "password": "Password1",
    })
    assert r.status_code == 200, r.text
    return r.json()