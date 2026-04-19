import logging
import secrets
import redis.asyncio as aioredis
from backend.config import get_settings

log = logging.getLogger(__name__)

class OTPError(Exception):
    pass

class OTPExpiredError(OTPError):
    pass

class OTPInvalidError(OTPError):
    pass

class OTPLockedError(OTPError):
    pass

class OTPCooldownError(OTPError):
    pass

class OTPService:
    OTP_KEY = "otp:{email}"
    COOLDOWN_KEY = "otp:cooldown:{email}"
    PENDING_KEY = "otp:pending:{email}"

    def __init__(self, redis: aioredis.Redis) -> None:
        self._r = redis
        self._settings = get_settings()

    def _otp_key(self, email: str) -> str:
        return f"otp:{email.lower()}"

    def _cooldown_key(self, email: str) -> str:
        return f"otp:cooldown:{email.lower()}"

    def _pending_key(self, email: str) -> str:
        return f"otp:pending:{email.lower()}"

    async def create_otp(self, email: str) -> str:
        email = email.lower()
        cooldown_key = self._cooldown_key(email)

        if await self._r.exists(cooldown_key):
            ttl = await self._r.ttl(cooldown_key)
            raise OTPCooldownError(
                f"Please wait {ttl} second(s) before requesting a new OTP."
            )

        code = self._generate_code()
        otp_key = self._otp_key(email)
        ttl = self._settings.otp_ttl_seconds
        cooldown = self._settings.otp_resend_cooldown_seconds
        pipe = self._r.pipeline()
        pipe.hset(otp_key, mapping={"code": code, "attempts": 0})
        pipe.expire(otp_key, ttl)
        pipe.set(cooldown_key, 1, ex=cooldown)
        pipe.set(self._pending_key(email), 1, ex=ttl)
        await pipe.execute()
        log.debug("OTP created for %s (ttl=%ds)", email, ttl)
        return code

    async def verify_otp(self, email: str, submitted: str) -> None:
        email = email.lower()
        otp_key = self._otp_key(email)

        data = await self._r.hgetall(otp_key)
        if not data:
            raise OTPExpiredError("OTP has expired or was never issued. Please request a new one.")

        stored_code: str = data["code"]
        attempts: int = int(data["attempts"])
        max_attempts = self._settings.otp_max_attempts

        if attempts >= max_attempts:
            await self._delete_otp_keys(email)
            raise OTPLockedError(
                f"Too many incorrect attempts. Please start the signup process again."
            )

        if not secrets.compare_digest(stored_code, submitted.strip()):
            new_attempts = attempts + 1
            remaining = max_attempts - new_attempts
            if new_attempts >= max_attempts:
                await self._delete_otp_keys(email)
                raise OTPLockedError(
                    "Too many incorrect attempts. Please start the signup process again."
                )
            await self._r.hset(otp_key, "attempts", new_attempts)
            raise OTPInvalidError(
                f"Incorrect OTP. {remaining} attempt(s) remaining."
            )
        await self._delete_otp_keys(email)
        log.debug("OTP verified for %s", email)

    async def is_signup_pending(self, email: str) -> bool:
        return bool(await self._r.exists(self._pending_key(email.lower())))

    async def cancel_pending(self, email: str) -> None:
        await self._delete_otp_keys(email.lower())

    @staticmethod
    def _generate_code() -> str:
        return f"{secrets.randbelow(1_000_000):06d}"

    async def _delete_otp_keys(self, email: str) -> None:
        pipe = self._r.pipeline()
        pipe.delete(self._otp_key(email))
        pipe.delete(self._pending_key(email))
        await pipe.execute()