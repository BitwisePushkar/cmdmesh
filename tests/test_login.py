import pytest
from httpx import AsyncClient
from datetime import datetime, timedelta, timezone
import jwt
from backend.config import get_settings

@pytest.mark.asyncio
async def test_login_with_username(client: AsyncClient, verified_user):
    r = await client.post("/auth/login", json={
        "identifier": "testuser",
        "password": "Password1",
    })
    assert r.status_code == 200
    body = r.json()
    assert "access_token" in body
    assert "refresh_token" in body
    assert body["token_type"] == "bearer"
    assert body["expires_in"] > 0

@pytest.mark.asyncio
async def test_login_with_email(client: AsyncClient, verified_user):
    r = await client.post("/auth/login", json={
        "identifier": "test@example.com",
        "password": "Password1",
    })
    assert r.status_code == 200
    assert "access_token" in r.json()

@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient, verified_user):
    r = await client.post("/auth/login", json={
        "identifier": "testuser",
        "password": "WrongPassword9",
    })
    assert r.status_code == 401
    assert "Invalid credentials" in r.json()["detail"]

@pytest.mark.asyncio
async def test_login_nonexistent_user(client: AsyncClient):
    r = await client.post("/auth/login", json={
        "identifier": "ghost",
        "password": "Password1",
    })
    assert r.status_code == 401
    assert "Invalid credentials" in r.json()["detail"]

@pytest.mark.asyncio
async def test_login_missing_fields(client: AsyncClient):
    r = await client.post("/auth/login", json={"identifier": "testuser"})
    assert r.status_code == 422

@pytest.mark.asyncio
async def test_login_username_case_insensitive(client: AsyncClient, verified_user):
    r = await client.post("/auth/login", json={
        "identifier": "TESTUSER",
        "password": "Password1",
    })
    assert r.status_code == 200

@pytest.mark.asyncio
async def test_login_email_case_insensitive(client: AsyncClient, verified_user):
    r = await client.post("/auth/login", json={
        "identifier": "TEST@EXAMPLE.COM",
        "password": "Password1",
    })
    assert r.status_code == 200

@pytest.mark.asyncio
async def test_me_authenticated(client: AsyncClient, auth_tokens):
    r = await client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {auth_tokens['access_token']}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["username"] == "testuser"
    assert body["email"] == "test@example.com"
    assert body["is_verified"] is True

@pytest.mark.asyncio
async def test_me_no_token(client: AsyncClient):
    r = await client.get("/auth/me")
    assert r.status_code == 401

@pytest.mark.asyncio
async def test_me_invalid_token(client: AsyncClient):
    r = await client.get(
        "/auth/me",
        headers={"Authorization": "Bearer this.is.not.a.jwt"},
    )
    assert r.status_code == 401

@pytest.mark.asyncio
async def test_me_expired_token(client: AsyncClient, verified_user):
    settings = get_settings()
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    payload = {
        "sub": str(verified_user.id),
        "jti": "test-jti",
        "username": verified_user.username,
        "email": verified_user.email,
        "iat": past,
        "exp": past + timedelta(minutes=15),
    }
    expired_token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    r = await client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert r.status_code == 401

@pytest.mark.asyncio
async def test_logout_success(client: AsyncClient, auth_tokens, db_session):
    r = await client.post("/auth/logout", json={
        "refresh_token": auth_tokens["refresh_token"],
    })
    assert r.status_code == 200
    assert "Logged out" in r.json()["message"]

@pytest.mark.asyncio
async def test_logout_then_refresh_fails(client: AsyncClient, auth_tokens):
    await client.post("/auth/logout", json={
        "refresh_token": auth_tokens["refresh_token"],
    })

    r = await client.post("/auth/refresh", json={
        "refresh_token": auth_tokens["refresh_token"],
    })
    assert r.status_code == 401

@pytest.mark.asyncio
async def test_logout_invalid_token_is_graceful(client: AsyncClient):
    r = await client.post("/auth/logout", json={"refresh_token": "garbage"})
    assert r.status_code == 200

@pytest.mark.asyncio
async def test_login_unverified_user(client: AsyncClient, db_session):
    from backend.models.user import User
    from backend.services.auth_service import AuthService
    unverified = User(
        username="unverified",
        email="unverified@example.com",
        hashed_password=AuthService.hash_password("Password1"),
        is_verified=False,
    )
    db_session.add(unverified)
    await db_session.commit()
    r = await client.post("/auth/login", json={
        "identifier": "unverified",
        "password": "Password1",
    })
    assert r.status_code == 403
    assert "verified" in r.json()["detail"].lower()