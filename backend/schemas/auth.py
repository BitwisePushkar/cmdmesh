import re
from typing import Annotated
from pydantic import BaseModel, EmailStr, Field, field_validator

USERNAME_RE = re.compile(r"^[a-zA-Z0-9_-]{3,32}$")

class SignupRequest(BaseModel):
    username: Annotated[str, Field(min_length=3, max_length=32)]
    email: EmailStr
    password: Annotated[str, Field(min_length=8, max_length=128)]
    @field_validator("username")
    @classmethod
    def username_valid(cls, v: str) -> str:
        if not USERNAME_RE.match(v):
            raise ValueError("Username must be 3-32 characters: letters, digits, _ or -")
        return v.lower()
    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        return v

class OTPVerifyRequest(BaseModel):
    email: EmailStr
    otp: Annotated[str, Field(min_length=6, max_length=6, pattern=r"^\d{6}$")]

class ResendOTPRequest(BaseModel):
    email: EmailStr

class LoginRequest(BaseModel):
    identifier: Annotated[str, Field(min_length=3, max_length=254)]
    password: Annotated[str, Field(min_length=1, max_length=128)]

class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1)

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int

class LogoutRequest(BaseModel):
    refresh_token: str = Field(min_length=1)

class PasswordResetRequestRequest(BaseModel):
    email: EmailStr

class PasswordResetConfirmRequest(BaseModel):
    email: EmailStr
    otp: Annotated[str, Field(min_length=6, max_length=6, pattern=r"^\d{6}$")]
    new_password: Annotated[str, Field(min_length=8, max_length=128)]
    @field_validator("new_password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        return v

class MessageResponse(BaseModel):
    message: str
    detail: str | None = None