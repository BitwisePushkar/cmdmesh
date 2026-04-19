import pytest
from httpx import AsyncClient

VALID_SIGNUP = {
    "username": "alice",
    "email": "alice@example.com",
    "password": "Secure123",
}

@pytest.mark.asyncio
async def test_signup_success(client: AsyncClient, mock_celery):
    r = await client.post("/auth/signup", json=VALID_SIGNUP)
    assert r.status_code == 202
    assert "Verification code sent" in r.json()["message"]
    mock_celery['otp'].assert_called_once()

@pytest.mark.asyncio
async def test_signup_missing_fields(client: AsyncClient):
    r = await client.post("/auth/signup", json={"username": "bob"})
    assert r.status_code == 422

@pytest.mark.asyncio
async def test_signup_weak_password_no_uppercase(client: AsyncClient):
    r = await client.post("/auth/signup", json={
        **VALID_SIGNUP, "password": "password123"
    })
    assert r.status_code == 422

@pytest.mark.asyncio
async def test_signup_weak_password_no_digit(client: AsyncClient):
    r = await client.post("/auth/signup", json={
        **VALID_SIGNUP, "password": "PasswordNoDigit"
    })
    assert r.status_code == 422

@pytest.mark.asyncio
async def test_signup_password_too_short(client: AsyncClient):
    r = await client.post("/auth/signup", json={
        **VALID_SIGNUP, "password": "Ab1"
    })
    assert r.status_code == 422

@pytest.mark.asyncio
async def test_signup_invalid_username_special_chars(client: AsyncClient):
    r = await client.post("/auth/signup", json={
        **VALID_SIGNUP, "username": "alice!"
    })
    assert r.status_code == 422

@pytest.mark.asyncio
async def test_signup_invalid_email(client: AsyncClient):
    r = await client.post("/auth/signup", json={
        **VALID_SIGNUP, "email": "not-an-email"
    })
    assert r.status_code == 422

@pytest.mark.asyncio
async def test_signup_duplicate_email(client: AsyncClient, verified_user, mock_celery):
    r = await client.post("/auth/signup", json={
        "username": "newuser",
        "email": "test@example.com",
        "password": "Password1",
    })
    assert r.status_code == 409
    assert "email" in r.json()["detail"].lower()

@pytest.mark.asyncio
async def test_signup_duplicate_username(client: AsyncClient, verified_user, mock_celery):
    r = await client.post("/auth/signup", json={
        "username": "testuser", 
        "email": "unique@example.com",
        "password": "Password1",
    })
    assert r.status_code == 409

@pytest.mark.asyncio
async def test_signup_resend_cooldown(client: AsyncClient, mock_celery):
    await client.post("/auth/signup", json=VALID_SIGNUP)
    r = await client.post("/auth/resend-otp", json={"email": VALID_SIGNUP["email"]})
    assert r.status_code == 429
    assert "wait" in r.json()["detail"].lower()

@pytest.mark.asyncio
async def test_verify_otp_wrong_code(client: AsyncClient, mock_celery, redis_client):
    await client.post("/auth/signup", json=VALID_SIGNUP)

    r = await client.post("/auth/verify-otp", json={
        "email": VALID_SIGNUP["email"],
        "otp": "000000",
    })
    assert r.status_code == 422
    assert "attempt" in r.json()["detail"].lower()

@pytest.mark.asyncio
async def test_verify_otp_wrong_format(client: AsyncClient):
    r = await client.post("/auth/verify-otp", json={
        "email": "any@example.com",
        "otp": "abc",
    })
    assert r.status_code == 422

@pytest.mark.asyncio
async def test_verify_otp_no_pending_signup(client: AsyncClient):
    r = await client.post("/auth/verify-otp", json={
        "email": "ghost@example.com",
        "otp": "123456",
    })
    assert r.status_code in (410, 422)

@pytest.mark.asyncio
async def test_verify_otp_max_attempts_locks(client: AsyncClient, mock_celery, test_settings):
    await client.post("/auth/signup", json=VALID_SIGNUP)
    for _ in range(test_settings.otp_max_attempts):
        r = await client.post("/auth/verify-otp", json={
            "email": VALID_SIGNUP["email"],
            "otp": "000000",
        })
    assert r.status_code in (422, 429)
    r2 = await client.post("/auth/verify-otp", json={
        "email": VALID_SIGNUP["email"],
        "otp": "000000",
    })
    assert r2.status_code in (410, 429)

@pytest.mark.asyncio
async def test_full_signup_flow(client: AsyncClient, mock_celery, redis_client):
    r = await client.post("/auth/signup", json=VALID_SIGNUP)
    assert r.status_code == 202
    otp_data = await redis_client.hgetall(f"otp:{VALID_SIGNUP['email']}")
    assert otp_data, "OTP key not found in Redis"
    code = otp_data["code"]
    r2 = await client.post("/auth/verify-otp", json={
        "email": VALID_SIGNUP["email"],
        "otp": code,
    })
    assert r2.status_code == 201
    assert "created" in r2.json()["message"].lower()
    leftover = await redis_client.hgetall(f"otp:{VALID_SIGNUP['email']}")
    assert not leftover

@pytest.mark.asyncio
async def test_resend_otp_no_pending(client: AsyncClient):
    r = await client.post("/auth/resend-otp", json={"email": "nobody@example.com"})
    assert r.status_code == 404

@pytest.mark.asyncio
async def test_resend_otp_after_cooldown(client: AsyncClient, mock_celery, redis_client, test_settings):
    await client.post("/auth/signup", json=VALID_SIGNUP)
    await redis_client.delete(f"otp:cooldown:{VALID_SIGNUP['email']}")

    r = await client.post("/auth/resend-otp", json={"email": VALID_SIGNUP["email"]})
    assert r.status_code == 200
    assert mock_celery['otp'].call_count == 2