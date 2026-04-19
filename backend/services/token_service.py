import hashlib
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from cryptography.fernet import Fernet, InvalidToken
import jwt
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError as JWTError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from backend.config import get_settings
from backend.models.token import RefreshToken
from backend.models.user import User

log = logging.getLogger(__name__)

class TokenError(Exception):
    pass

class TokenExpiredError(TokenError):
    pass

class TokenRevokedError(TokenError):
    pass

class TokenInvalidError(TokenError):
    pass

class TokenService:
    @staticmethod
    def _fernet() -> Fernet:
        key = get_settings().token_encryption_key
        if not key:
            raise RuntimeError("TOKEN_ENCRYPTION_KEY is not configured")
        return Fernet(key.encode() if isinstance(key, str) else key)

    @staticmethod
    def encrypt_token(plaintext: str) -> str:
        return TokenService._fernet().encrypt(plaintext.encode()).decode()

    @staticmethod
    def decrypt_token(ciphertext: str) -> str:
        try:
            return TokenService._fernet().decrypt(ciphertext.encode()).decode()
        except InvalidToken as exc:
            raise TokenInvalidError("Refresh token is corrupted or tampered.") from exc

    @staticmethod
    def create_access_token(user: User) -> tuple[str, int]:
        settings = get_settings()
        expire_seconds = settings.access_token_expire_minutes * 60
        now = datetime.now(timezone.utc)
        expire = now + timedelta(seconds=expire_seconds)
        payload: dict[str, Any] = {
            "sub": str(user.id),
            "jti": secrets.token_hex(16),
            "username": user.username,
            "email": user.email,
            "iat": now,
            "exp": expire,
        }
        token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
        return token, expire_seconds

    @staticmethod
    def decode_access_token(token: str) -> dict[str, Any]:
        settings = get_settings()
        try:
            payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
            return payload
        except ExpiredSignatureError as exc:
            raise TokenExpiredError("Access token has expired.") from exc
        except JWTError as exc:
            raise TokenInvalidError(f"Invalid access token: {exc}") from exc

    @classmethod
    async def create_refresh_token(cls, db: AsyncSession, user: User, device_fingerprint: str | None = None) -> str:
        settings = get_settings()
        jti = secrets.token_hex(32)
        expires_at = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
        record = RefreshToken(jti=jti, user_id=user.id, device_fingerprint=device_fingerprint, expires_at=expires_at)
        db.add(record)
        await db.flush()
        plaintext = jti
        return cls.encrypt_token(plaintext)

    @classmethod
    async def rotate_refresh_token(cls, db: AsyncSession, encrypted_token: str, device_fingerprint: str | None = None) -> tuple[User, str, str, int]:
        jti = cls.decrypt_token(encrypted_token)
        result = await db.execute(select(RefreshToken).where(RefreshToken.jti == jti))
        record = result.scalar_one_or_none()
        if record is None:
            raise TokenInvalidError("Refresh token not found.")
        now = datetime.now(timezone.utc)
        if record.is_revoked:
            log.warning("Refresh token reuse detected for user_id=%s, revoking all sessions.", record.user_id)
            await cls._revoke_all_user_tokens(db, record.user_id)
            raise TokenRevokedError("Refresh token was already used. All sessions have been invalidated. Please log in again.")
        if record.expires_at.replace(tzinfo=timezone.utc) < now:
            raise TokenExpiredError("Refresh token has expired. Please log in again.")
        user_result = await db.execute(select(User).where(User.id == record.user_id))
        user = user_result.scalar_one_or_none()
        if user is None or not user.is_active:
            raise TokenInvalidError("Associated user account not found or disabled.")
        record.is_revoked = True
        record.revoked_at = now
        access_token, expires_in = cls.create_access_token(user)
        new_encrypted_refresh = await cls.create_refresh_token(db, user, device_fingerprint)
        return user, access_token, new_encrypted_refresh, expires_in

    @classmethod
    async def revoke_token(cls, db: AsyncSession, encrypted_token: str) -> None:
        try:
            jti = cls.decrypt_token(encrypted_token)
        except TokenInvalidError:
            return
        await db.execute(update(RefreshToken).where(RefreshToken.jti == jti, RefreshToken.is_revoked.is_(False)).values(is_revoked=True, revoked_at=datetime.now(timezone.utc)))

    @staticmethod
    async def _revoke_all_user_tokens(db: AsyncSession, user_id: uuid.UUID) -> None:
        await db.execute(update(RefreshToken).where(RefreshToken.user_id == user_id, RefreshToken.is_revoked.is_(False)).values(is_revoked=True, revoked_at=datetime.now(timezone.utc)))

    @staticmethod
    def make_device_fingerprint(hostname: str, platform: str) -> str:
        raw = f"{hostname}:{platform}"
        return hashlib.sha256(raw.encode()).hexdigest()