import json
import os
import stat
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import TypedDict
from rich.console import Console

console = Console(stderr=True)

CREDENTIALS_DIR = Path.home() / ".cmdmesh"
CREDENTIALS_FILE = CREDENTIALS_DIR / "credentials"

class Credentials(TypedDict):
    access_token: str
    refresh_token: str      
    expires_at: str       
    username: str
    email: str
    user_id: str

class CredentialStore:
    @staticmethod
    def save(
        *,
        access_token: str,
        refresh_token: str,
        expires_in: int,
        username: str,
        email: str,
        user_id: str,
    ) -> None:
        CREDENTIALS_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        ).isoformat()
        data: Credentials = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": expires_at,
            "username": username,
            "email": email,
            "user_id": user_id,
        }
        tmp = CREDENTIALS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR) 
        tmp.replace(CREDENTIALS_FILE)

    @staticmethod
    def load() -> Credentials | None:
        if not CREDENTIALS_FILE.exists():
            return None
        try:
            data = json.loads(CREDENTIALS_FILE.read_text())
            required = {"access_token", "refresh_token", "expires_at", "username", "email"}
            if not required.issubset(data.keys()):
                return None
            return data 
        except (json.JSONDecodeError, OSError):
            return None

    @staticmethod
    def get_access_token() -> str | None:
        creds = CredentialStore.load()
        return creds["access_token"] if creds else None

    @staticmethod
    def get_refresh_token() -> str | None:
        creds = CredentialStore.load()
        return creds["refresh_token"] if creds else None

    @staticmethod
    def is_access_token_expired() -> bool:
        creds = CredentialStore.load()
        if not creds:
            return True
        try:
            expires_at = datetime.fromisoformat(creds["expires_at"])
            return datetime.now(timezone.utc).timestamp() >= (expires_at.timestamp() - 30)
        except (ValueError, KeyError):
            return True

    @staticmethod
    def is_logged_in() -> bool:
        return CredentialStore.load() is not None

    @staticmethod
    def clear() -> None:
        if CREDENTIALS_FILE.exists():
            CREDENTIALS_FILE.unlink()

    @staticmethod
    def update_tokens(
        *,
        access_token: str,
        refresh_token: str,
        expires_in: int,
    ) -> None:
        creds = CredentialStore.load()
        if not creds:
            raise RuntimeError("No existing credentials to update.")
        CredentialStore.save(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=expires_in,
            username=creds["username"],
            email=creds["email"],
            user_id=creds.get("user_id", ""),
        )