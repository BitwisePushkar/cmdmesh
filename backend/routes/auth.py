import json
import logging
from typing import Annotated
from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
import redis.asyncio as aioredis
from backend.dependencies.auth import CurrentUser
from backend.dependencies.db import get_db
from backend.dependencies.redis import get_redis
from backend.schemas.auth import (
    LoginRequest, LogoutRequest, MessageResponse, OTPVerifyRequest,
    PasswordResetConfirmRequest, PasswordResetRequestRequest,
    RefreshRequest, ResendOTPRequest, SignupRequest, TokenResponse,
)
from backend.schemas.user import UserPublic
from backend.services.auth_service import (
    AccountDisabledError, AccountNotVerifiedError, AuthService, ConflictError, CredentialsError,
)
from backend.services.otp_service import (
    OTPCooldownError, OTPExpiredError, OTPInvalidError, OTPLockedError, OTPService,
)
from backend.services.password_reset_service import (
    PasswordResetCooldownError, PasswordResetExpiredError, PasswordResetInvalidError,
    PasswordResetLockedError, PasswordResetService,
)
from backend.services.token_service import (
    TokenExpiredError, TokenInvalidError, TokenRevokedError, TokenService,
)
from backend.models.token import RefreshToken

log = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

SIGNUP_DATA_KEY = "signup:data:{email}"
SIGNUP_DATA_TTL = 600

async def _store_signup_data(redis: aioredis.Redis, data: SignupRequest) -> None:
    key = SIGNUP_DATA_KEY.format(email=data.email.lower())
    payload = json.dumps({
        "username": data.username,
        "email": data.email.lower(),
        "password": data.password,
    })
    await redis.set(key, payload, ex=SIGNUP_DATA_TTL)

async def _load_signup_data(redis: aioredis.Redis, email: str) -> SignupRequest | None:
    key = SIGNUP_DATA_KEY.format(email=email.lower())
    raw = await redis.get(key)
    if not raw:
        return None
    try:
        return SignupRequest(**json.loads(raw))
    except Exception:
        return None

async def _delete_signup_data(redis: aioredis.Redis, email: str) -> None:
    await redis.delete(SIGNUP_DATA_KEY.format(email=email.lower()))

@router.post("/signup", response_model=MessageResponse, status_code=status.HTTP_202_ACCEPTED)
async def signup(
    data: SignupRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
) -> MessageResponse:
    try:
        await AuthService.check_uniqueness(db, data.username, data.email)
    except ConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    otp_svc = OTPService(redis)
    try:
        code = await otp_svc.create_otp(data.email)
    except OTPCooldownError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc))
    await _store_signup_data(redis, data)
    from backend.tasks.email_tasks import send_otp_email
    send_otp_email.delay(email=data.email, username=data.username, otp=code)
    return MessageResponse(
        message="Verification code sent",
        detail=f"A 6-digit OTP has been sent to {data.email}. It expires in 10 minutes.",
    )

@router.post("/verify-otp", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
async def verify_otp(
    data: OTPVerifyRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
) -> MessageResponse:
    otp_svc = OTPService(redis)
    try:
        await otp_svc.verify_otp(data.email, data.otp)
    except OTPExpiredError as exc:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail=str(exc))
    except OTPInvalidError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except OTPLockedError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc))
    signup_data = await _load_signup_data(redis, data.email)
    if not signup_data:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Signup session has expired. Please start again.")
    try:
        await AuthService.check_uniqueness(db, signup_data.username, signup_data.email)
    except ConflictError as exc:
        await _delete_signup_data(redis, data.email)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    await AuthService.create_verified_user(db, signup_data)
    await _delete_signup_data(redis, data.email)
    return MessageResponse(
        message="Account created",
        detail="Your account has been verified. Run `cmdmesh login` to get started.",
    )

@router.post("/resend-otp", response_model=MessageResponse)
async def resend_otp(
    data: ResendOTPRequest,
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
) -> MessageResponse:
    otp_svc = OTPService(redis)
    if not await otp_svc.is_signup_pending(data.email):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No pending signup for this email. Run `cmdmesh signup` first.")
    signup_data = await _load_signup_data(redis, data.email)
    username = signup_data.username if signup_data else "there"
    try:
        code = await otp_svc.create_otp(data.email)
    except OTPCooldownError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc))
    from backend.tasks.email_tasks import send_otp_email
    send_otp_email.delay(email=data.email, username=username, otp=code)
    return MessageResponse(message="OTP resent", detail="New code sent to your email.")

@router.post("/login", response_model=TokenResponse)
async def login(
    data: LoginRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    x_device_hostname: Annotated[str | None, Header()] = None,
    x_device_platform: Annotated[str | None, Header()] = None,
) -> TokenResponse:
    try:
        user = await AuthService.authenticate(db, data)
    except CredentialsError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))
    except AccountNotVerifiedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except AccountDisabledError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    fingerprint = None
    if x_device_hostname and x_device_platform:
        fingerprint = TokenService.make_device_fingerprint(x_device_hostname, x_device_platform)
    access_token, expires_in = TokenService.create_access_token(user)
    encrypted_refresh = await TokenService.create_refresh_token(db, user, fingerprint)
    return TokenResponse(access_token=access_token, refresh_token=encrypted_refresh, expires_in=expires_in)

@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    data: RefreshRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    x_device_hostname: Annotated[str | None, Header()] = None,
    x_device_platform: Annotated[str | None, Header()] = None,
) -> TokenResponse:
    fingerprint = None
    if x_device_hostname and x_device_platform:
        fingerprint = TokenService.make_device_fingerprint(x_device_hostname, x_device_platform)
    try:
        _user, access_token, new_refresh, expires_in = await TokenService.rotate_refresh_token(db, data.refresh_token, fingerprint)
    except TokenRevokedError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc), headers={"X-Logout-Required": "true"})
    except TokenExpiredError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc), headers={"X-Logout-Required": "true"})
    except TokenInvalidError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))
    return TokenResponse(access_token=access_token, refresh_token=new_refresh, expires_in=expires_in)

@router.post("/logout", response_model=MessageResponse)
async def logout(data: LogoutRequest, db: Annotated[AsyncSession, Depends(get_db)]) -> MessageResponse:
    await TokenService.revoke_token(db, data.refresh_token)
    return MessageResponse(message="Logged out successfully.")

@router.get("/me", response_model=UserPublic)
async def me(current_user: CurrentUser) -> UserPublic:
    return UserPublic.model_validate(current_user)

@router.post("/reset-password/request", response_model=MessageResponse, status_code=status.HTTP_202_ACCEPTED)
async def reset_password_request(
    data: PasswordResetRequestRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
) -> MessageResponse:
    reset_svc = PasswordResetService(redis)
    user = await PasswordResetService.lookup_user(db, data.email)
    if user and user.is_active:
        try:
            code = await reset_svc.create_otp(data.email)
        except PasswordResetCooldownError as exc:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc))
        from backend.tasks.email_tasks import send_password_reset_email
        send_password_reset_email.delay(email=data.email, username=user.username, otp=code)
    return MessageResponse(message="If that email is registered, a reset code has been sent.", detail="Check your inbox. The code expires in 5 minutes.")

@router.post("/reset-password/confirm", response_model=MessageResponse, status_code=status.HTTP_200_OK)
async def reset_password_confirm(
    data: PasswordResetConfirmRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
) -> MessageResponse:
    reset_svc = PasswordResetService(redis)
    try:
        await reset_svc.verify_otp(data.email, data.otp)
    except PasswordResetExpiredError as exc:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail=str(exc))
    except PasswordResetInvalidError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except PasswordResetLockedError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc))
    user = await PasswordResetService.lookup_user(db, data.email)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found.")
    if AuthService.verify_password(data.new_password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="New password must be different from your current password.")
    user.hashed_password = AuthService.hash_password(data.new_password)
    await db.execute(update(RefreshToken).where(RefreshToken.user_id == user.id, RefreshToken.is_revoked.is_(False)).values(is_revoked=True))
    log.info("Password reset completed for user %s", user.username)
    return MessageResponse(message="Password reset successful.", detail="All existing sessions have been invalidated. Run `cmdmesh login`.")