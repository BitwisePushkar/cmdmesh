import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_reset_request_registered_email(client: AsyncClient, verified_user, mock_celery):
    r = await client.post("/auth/reset-password/request", json={
        "email": "test@example.com",
    })
    assert r.status_code == 202
    assert "reset code" in r.json()["message"].lower() or "registered" in r.json()["message"].lower()
    mock_celery["reset"].assert_called_once()

@pytest.mark.asyncio
async def test_reset_request_unknown_email_returns_202(client: AsyncClient, mock_celery):
    r = await client.post("/auth/reset-password/request", json={
        "email": "nobody@example.com",
    })
    assert r.status_code == 202
    mock_celery["reset"].assert_not_called()

@pytest.mark.asyncio
async def test_reset_request_invalid_email(client: AsyncClient):
    r = await client.post("/auth/reset-password/request", json={"email": "not-an-email"})
    assert r.status_code == 422

@pytest.mark.asyncio
async def test_reset_request_cooldown(client: AsyncClient, verified_user, mock_celery):
    await client.post("/auth/reset-password/request", json={"email": "test@example.com"})
    r = await client.post("/auth/reset-password/request", json={"email": "test@example.com"})
    assert r.status_code == 429
    assert "wait" in r.json()["detail"].lower()

@pytest.mark.asyncio
async def test_reset_confirm_happy_path(
    client: AsyncClient, verified_user, redis_client, mock_celery
):
    await client.post("/auth/reset-password/request", json={"email": "test@example.com"})

    otp_data = await redis_client.hgetall("pwreset:test@example.com")
    assert otp_data, "Reset OTP key not found in Redis"
    code = otp_data["code"]

    r = await client.post("/auth/reset-password/confirm", json={
        "email": "test@example.com",
        "otp": code,
        "new_password": "NewSecure9",
    })
    assert r.status_code == 200
    assert "successful" in r.json()["message"].lower()

@pytest.mark.asyncio
async def test_reset_confirm_wrong_otp(
    client: AsyncClient, verified_user, mock_celery
):
    await client.post("/auth/reset-password/request", json={"email": "test@example.com"})
    r = await client.post("/auth/reset-password/confirm", json={
        "email": "test@example.com",
        "otp": "000000",
        "new_password": "NewSecure9",
    })
    assert r.status_code == 422
    assert "attempt" in r.json()["detail"].lower()

@pytest.mark.asyncio
async def test_reset_confirm_max_attempts_locks(
    client: AsyncClient, verified_user, mock_celery, test_settings
):
    await client.post("/auth/reset-password/request", json={"email": "test@example.com"})

    for _ in range(test_settings.password_reset_otp_max_attempts):
        r = await client.post("/auth/reset-password/confirm", json={
            "email": "test@example.com",
            "otp": "000000",
            "new_password": "NewSecure9",
        })

    assert r.status_code in (422, 429)
    r2 = await client.post("/auth/reset-password/confirm", json={
        "email": "test@example.com",
        "otp": "000000",
        "new_password": "NewSecure9",
    })
    assert r2.status_code in (410, 429)

@pytest.mark.asyncio
async def test_reset_confirm_no_otp_issued(client: AsyncClient, verified_user):
    r = await client.post("/auth/reset-password/confirm", json={
        "email": "test@example.com",
        "otp": "123456",
        "new_password": "NewSecure9",
    })
    assert r.status_code == 410

@pytest.mark.asyncio
async def test_reset_confirm_rejects_same_password(
    client: AsyncClient, verified_user, redis_client, mock_celery
):
    await client.post("/auth/reset-password/request", json={"email": "test@example.com"})
    otp_data = await redis_client.hgetall("pwreset:test@example.com")
    code = otp_data["code"]

    r = await client.post("/auth/reset-password/confirm", json={
        "email": "test@example.com",
        "otp": code,
        "new_password": "Password1",
    })
    assert r.status_code == 422
    assert "different" in r.json()["detail"].lower()

@pytest.mark.asyncio
async def test_reset_confirm_weak_new_password(
    client: AsyncClient, verified_user, redis_client, mock_celery
):
    await client.post("/auth/reset-password/request", json={"email": "test@example.com"})
    otp_data = await redis_client.hgetall("pwreset:test@example.com")
    code = otp_data["code"]
    r = await client.post("/auth/reset-password/confirm", json={
        "email": "test@example.com",
        "otp": code,
        "new_password": "weakpassword",
    })
    assert r.status_code == 422

@pytest.mark.asyncio
async def test_reset_confirm_invalidates_all_sessions(
    client: AsyncClient, verified_user, auth_tokens, redis_client, mock_celery
):
    existing_refresh = auth_tokens["refresh_token"]
    await client.post("/auth/reset-password/request", json={"email": "test@example.com"})
    otp_data = await redis_client.hgetall("pwreset:test@example.com")
    code = otp_data["code"]

    r = await client.post("/auth/reset-password/confirm", json={
        "email": "test@example.com",
        "otp": code,
        "new_password": "FreshPass9",
    })
    assert r.status_code == 200

    r2 = await client.post("/auth/refresh", json={"refresh_token": existing_refresh})
    assert r2.status_code == 401

@pytest.mark.asyncio
async def test_reset_then_login_with_new_password(
    client: AsyncClient, verified_user, redis_client, mock_celery
):
    await client.post("/auth/reset-password/request", json={"email": "test@example.com"})
    otp_data = await redis_client.hgetall("pwreset:test@example.com")
    code = otp_data["code"]

    await client.post("/auth/reset-password/confirm", json={
        "email": "test@example.com",
        "otp": code,
        "new_password": "BrandNew9",
    })

    r = await client.post("/auth/login", json={
        "identifier": "testuser",
        "password": "BrandNew9",
    })
    assert r.status_code == 200

    r2 = await client.post("/auth/login", json={
        "identifier": "testuser",
        "password": "Password1",
    })
    assert r2.status_code == 401