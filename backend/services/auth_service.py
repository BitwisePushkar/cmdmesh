import logging
import bcrypt
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from backend.models.user import User
from backend.schemas.auth import LoginRequest, SignupRequest

log = logging.getLogger(__name__)

class AuthError(Exception):
    pass

class ConflictError(AuthError):
    pass

class CredentialsError(AuthError):
    pass

class AccountNotVerifiedError(AuthError):
    pass

class AccountDisabledError(AuthError):
    pass

class AuthService:
    @staticmethod
    def hash_password(password: str) -> str:
        salt = bcrypt.gensalt(rounds=12)
        return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

    @staticmethod
    def verify_password(plain: str, hashed: str) -> bool:
        return bcrypt.checkpw(plain.encode('utf-8'), hashed.encode('utf-8'))

    @staticmethod
    async def check_uniqueness(db: AsyncSession, username: str, email: str) -> None:
        result = await db.execute(select(User).where(or_(User.username == username.lower(), User.email == email.lower())))
        existing = result.scalar_one_or_none()
        if existing:
            if existing.email == email.lower():
                raise ConflictError("An account with this email already exists.")
            raise ConflictError("Username is already taken.")

    @staticmethod
    async def create_verified_user(db: AsyncSession, data: SignupRequest) -> User:
        user = User(
            username=data.username.lower(),
            email=data.email.lower(),
            hashed_password=AuthService.hash_password(data.password),
            is_verified=True,
            is_active=True,
        )
        db.add(user)
        await db.flush()
        log.info("User created: %s (%s)", user.username, user.email)
        return user

    @staticmethod
    async def authenticate(db: AsyncSession, data: LoginRequest) -> User:
        identifier = data.identifier.lower().strip()
        if "@" in identifier:
            stmt = select(User).where(User.email == identifier)
        else:
            stmt = select(User).where(User.username == identifier)
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()
        dummy_hash = "$2b$12$KIXNp9G7pYGfBHhf1C7ChuN3L.mUJmU2TBBb5hFx/wQI.3gK3ZWFC"
        password_ok = AuthService.verify_password(data.password, user.hashed_password if user else dummy_hash)
        if not user or not password_ok:
            raise CredentialsError("Invalid credentials.")
        if not user.is_verified:
            raise AccountNotVerifiedError("Account not verified. Please complete OTP verification.")
        if not user.is_active:
            raise AccountDisabledError("Account is disabled. Contact support.")
        return user