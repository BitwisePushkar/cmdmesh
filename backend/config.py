from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
import os

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.getenv("ENV_FILE", ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
    database_url: str = "postgresql+asyncpg://cmdmesh:secret@localhost:5432/cmdmesh"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret_key: str = "insecure-dev-secret-change-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7
    token_encryption_key: str = ""
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = "noreply@cmdmesh.dev"
    smtp_tls: bool = False
    smtp_starttls: bool = False
    otp_ttl_seconds: int = 600
    otp_max_attempts: int = 5
    otp_resend_cooldown_seconds: int = 60
    password_reset_otp_ttl_seconds: int = 300
    password_reset_otp_max_attempts: int = 5
    password_reset_otp_cooldown_seconds: int = 60
    app_env: str = "development"
    backend_url: str = "http://localhost:8000"
    chat_session_ttl_seconds: int = 7200
    chat_max_context_messages: int = 20

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()