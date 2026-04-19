import pytest
from httpx import AsyncClient
from cryptography.fernet import Fernet
from backend.services.token_service import TokenService, TokenInvalidError
from unittest.mock import patch
from httpx import AsyncClient as AC, ASGITransport
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, update
from backend.models.token import RefreshToken

@pytest.mark.asyncio
async def test_refresh_returns_new_tokens(client: AsyncClient, auth_tokens):
    r = await client.post("/auth/refresh", json={
        "refresh_token": auth_tokens["refresh_token"],
    })
    assert r.status_code == 200
    body = r.json()
    assert "access_token" in body
    assert "refresh_token" in body
    assert body["access_token"] != auth_tokens["access_token"]
    assert body["refresh_token"] != auth_tokens["refresh_token"]

@pytest.mark.asyncio
async def test_refreshed_access_token_works(client: AsyncClient, auth_tokens):
    refresh_r = await client.post("/auth/refresh", json={
        "refresh_token": auth_tokens["refresh_token"],
    })
    new_access = refresh_r.json()["access_token"]
    me_r = await client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {new_access}"},
    )
    assert me_r.status_code == 200
    assert me_r.json()["username"] == "testuser"

@pytest.mark.asyncio
async def test_refresh_chain(client: AsyncClient, auth_tokens):
    current_refresh = auth_tokens["refresh_token"]
    for i in range(3):
        r = await client.post("/auth/refresh", json={"refresh_token": current_refresh})
        assert r.status_code == 200, f"Chain rotation {i+1} failed: {r.text}"
        current_refresh = r.json()["refresh_token"]

@pytest.mark.asyncio
async def test_old_refresh_token_rejected_after_rotation(client: AsyncClient, auth_tokens):
    original_refresh = auth_tokens["refresh_token"]
    await client.post("/auth/refresh", json={"refresh_token": original_refresh})
    r = await client.post("/auth/refresh", json={"refresh_token": original_refresh})
    assert r.status_code == 401

@pytest.mark.asyncio
async def test_refresh_token_reuse_revokes_all_sessions(
    client: AsyncClient, auth_tokens, verified_user
):
    original_refresh = auth_tokens["refresh_token"]
    r1 = await client.post("/auth/refresh", json={"refresh_token": original_refresh})
    assert r1.status_code == 200
    new_refresh = r1.json()["refresh_token"]
    r2 = await client.post("/auth/refresh", json={"refresh_token": original_refresh})
    assert r2.status_code == 401
    assert "revoked" in r2.json()["detail"].lower() or "invalidated" in r2.json()["detail"].lower()
    r3 = await client.post("/auth/refresh", json={"refresh_token": new_refresh})
    assert r3.status_code == 401

@pytest.mark.asyncio
async def test_refresh_with_garbage_token(client: AsyncClient):
    r = await client.post("/auth/refresh", json={"refresh_token": "not-a-real-token"})
    assert r.status_code == 401

@pytest.mark.asyncio
async def test_refresh_with_tampered_ciphertext(client: AsyncClient, auth_tokens):
    rt = auth_tokens["refresh_token"]
    tampered = rt[:-4] + "XXXX"

    r = await client.post("/auth/refresh", json={"refresh_token": tampered})
    assert r.status_code == 401

@pytest.mark.asyncio
async def test_refresh_missing_body(client: AsyncClient):
    r = await client.post("/auth/refresh", json={})
    assert r.status_code == 422

@pytest.mark.asyncio
async def test_expired_refresh_token_rejected(client: AsyncClient, db_session, verified_user):
    access, _ = TokenService.create_access_token(verified_user)
    encrypted_rt = await TokenService.create_refresh_token(db_session, verified_user)
    await db_session.commit()
    jti = TokenService.decrypt_token(encrypted_rt)
    past = datetime.now(timezone.utc) - timedelta(days=1)
    await db_session.execute(
        update(RefreshToken)
        .where(RefreshToken.jti == jti)
        .values(expires_at=past)
    )
    await db_session.commit()
    r = await client.post("/auth/refresh", json={"refresh_token": encrypted_rt})
    assert r.status_code == 401
    assert "expired" in r.json()["detail"].lower()

@pytest.mark.asyncio
async def test_refresh_token_is_encrypted(auth_tokens):
    rt = auth_tokens["refresh_token"]
    assert rt.startswith("gAAA") or len(rt) > 100, \
        "Refresh token does not look like Fernet ciphertext"
    parts = rt.split(".")
    assert len(parts) != 3, "Refresh token looks like a plain JWT — should be encrypted"

@pytest.mark.asyncio
async def test_token_encryption_roundtrip(test_settings):
    original = "some-secret-jti-value"
    encrypted = TokenService.encrypt_token(original)
    assert encrypted != original
    decrypted = TokenService.decrypt_token(encrypted)
    assert decrypted == original

@pytest.mark.asyncio
async def test_token_decryption_rejects_wrong_key():
    key_a = Fernet.generate_key().decode()
    key_b = Fernet.generate_key().decode()

    with patch("backend.services.token_service.get_settings") as mock_settings:
        mock_settings.return_value.token_encryption_key = key_a
        encrypted = TokenService.encrypt_token("secret-value")

    with patch("backend.services.token_service.get_settings") as mock_settings:
        mock_settings.return_value.token_encryption_key = key_b
        with pytest.raises(TokenInvalidError):
            TokenService.decrypt_token(encrypted)