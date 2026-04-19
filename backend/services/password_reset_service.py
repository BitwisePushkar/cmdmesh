import logging
import secrets
import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from backend.config import get_settings
from backend.models.user import User

log = logging.getLogger(__name__)

class PasswordResetError(Exception):
    pass

class PasswordResetExpiredError(PasswordResetError):
    pass

class PasswordResetInvalidError(PasswordResetError):
    pass

class PasswordResetLockedError(PasswordResetError):
    pass

class PasswordResetCooldownError(PasswordResetError):
    pass

class PasswordResetService:
    def __init__(self, redis: aioredis.Redis) -> None:
        self._r = redis
        self._settings = get_settings()

    def _otp_key(self, email: str) -> str:
        return f"pwreset:{email.lower()}"

    def _cooldown_key(self, email: str) -> str:
        return f"pwreset:cooldown:{email.lower()}"

    async def create_otp(self, email: str) -> str:
        email = email.lower()
        cooldown_key = self._cooldown_key(email)

        if await self._r.exists(cooldown_key):
            ttl = await self._r.ttl(cooldown_key)
            raise PasswordResetCooldownError(
                f"Please wait {ttl} second(s) before requesting another reset code."
            )

        code = self._generate_code()
        otp_key = self._otp_key(email)
        ttl = self._settings.password_reset_otp_ttl_seconds
        cooldown = self._settings.password_reset_otp_cooldown_seconds

        pipe = self._r.pipeline()
        pipe.hset(otp_key, mapping={"code": code, "attempts": 0})
        pipe.expire(otp_key, ttl)
        pipe.set(cooldown_key, 1, ex=cooldown)
        await pipe.execute()

        log.debug("Password-reset OTP created for %s (ttl=%ds)", email, ttl)
        return code

    async def verify_otp(self, email: str, submitted: str) -> None:
        email = email.lower()
        otp_key = self._otp_key(email)

        data = await self._r.hgetall(otp_key)
        if not data:
            raise PasswordResetExpiredError(
                "Reset code has expired or was never issued. Request a new one."
            )

        stored_code: str = data["code"]
        attempts: int = int(data["attempts"])
        max_attempts = self._settings.password_reset_otp_max_attempts

        if attempts >= max_attempts:
            await self._r.delete(otp_key)
            raise PasswordResetLockedError(
                "Too many incorrect attempts. Please request a new reset code."
            )

        if not secrets.compare_digest(stored_code, submitted.strip()):
            new_attempts = attempts + 1
            remaining = max_attempts - new_attempts
            if new_attempts >= max_attempts:
                await self._r.delete(otp_key)
                raise PasswordResetLockedError(
                    "Too many incorrect attempts. Please request a new reset code."
                )
            await self._r.hset(otp_key, "attempts", new_attempts)
            raise PasswordResetInvalidError(
                f"Incorrect code. {remaining} attempt(s) remaining."
            )
        await self._r.delete(otp_key)
        log.debug("Password-reset OTP verified for %s", email)

    @staticmethod
    def _generate_code() -> str:
        return f"{secrets.randbelow(1_000_000):06d}"

    @staticmethod
    async def lookup_user(db: AsyncSession, email: str) -> User | None:
        result = await db.execute(
            select(User).where(User.email == email.lower())
        )
        return result.scalar_one_or_none()