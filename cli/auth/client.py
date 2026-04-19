import platform
import socket
from typing import Any
import httpx
from cli.auth.store import CredentialStore

_BASE_URL: str = "http://localhost:8000"

def _device_headers() -> dict[str, str]:
    return {
        "X-Device-Hostname": socket.gethostname()[:64],
        "X-Device-Platform": platform.system()[:32],
    }

class APIError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"HTTP {status_code}: {detail}")

def _extract_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
        if isinstance(body.get("detail"), str):
            return body["detail"]
        if isinstance(body.get("detail"), list):
            return "; ".join(e.get("msg", str(e)) for e in body["detail"])
        if "errors" in body:
            return "; ".join(
                f"{e['field']}: {e['message']}" for e in body["errors"]
            )
        return response.text[:200]
    except Exception:
        return response.text[:200]

def _raise_for_status(response: httpx.Response) -> None:
    if response.status_code < 400:
        return
    raise APIError(response.status_code, _extract_detail(response))

def _make_client(token: str | None = None) -> httpx.Client:
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    headers.update(_device_headers())
    return httpx.Client(base_url=_BASE_URL, headers=headers, timeout=15.0)

def post_signup(username: str, email: str, password: str) -> dict[str, Any]:
    with _make_client() as client:
        r = client.post("/auth/signup", json={
            "username": username, "email": email, "password": password,
        })
        _raise_for_status(r)
        return r.json()

def post_verify_otp(email: str, otp: str) -> dict[str, Any]:
    with _make_client() as client:
        r = client.post("/auth/verify-otp", json={"email": email, "otp": otp})
        _raise_for_status(r)
        return r.json()

def post_resend_otp(email: str) -> dict[str, Any]:
    with _make_client() as client:
        r = client.post("/auth/resend-otp", json={"email": email})
        _raise_for_status(r)
        return r.json()

def post_login(identifier: str, password: str) -> dict[str, Any]:
    with _make_client() as client:
        r = client.post("/auth/login", json={"identifier": identifier, "password": password})
        _raise_for_status(r)
        return r.json()

def post_refresh(refresh_token: str) -> dict[str, Any]:
    with _make_client() as client:
        r = client.post("/auth/refresh", json={"refresh_token": refresh_token})
        _raise_for_status(r)
        return r.json()

def post_logout(refresh_token: str) -> dict[str, Any]:
    with _make_client() as client:
        r = client.post("/auth/logout", json={"refresh_token": refresh_token})
        _raise_for_status(r)
        return r.json()

def get_me() -> dict[str, Any]:
    token = CredentialStore.get_access_token()
    with _make_client(token=token) as client:
        r = client.get("/auth/me")
    if r.status_code == 401:
        new_token = _silent_refresh()
        if new_token is None:
            raise APIError(401, "Session expired. Please run `cmdmesh login`.")
        with _make_client(token=new_token) as client:
            r = client.get("/auth/me")
    _raise_for_status(r)
    return r.json()

def _silent_refresh() -> str | None:
    rt = CredentialStore.get_refresh_token()
    if not rt:
        return None
    try:
        data = post_refresh(rt)
        CredentialStore.update_tokens(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_in=data["expires_in"],
        )
        return data["access_token"]
    except APIError:
        return None

def authenticated_get(path: str, **kwargs) -> dict[str, Any]:
    return _authenticated_request("GET", path, **kwargs)

def authenticated_post(path: str, **kwargs) -> dict[str, Any]:
    return _authenticated_request("POST", path, **kwargs)

def _authenticated_request(method: str, path: str, **kwargs) -> dict[str, Any]:
    token = CredentialStore.get_access_token()
    with _make_client(token=token) as client:
        r = client.request(method, path, **kwargs)
    if r.status_code == 401:
        new_token = _silent_refresh()
        if new_token is None:
            raise APIError(401, "Session expired. Please run `cmdmesh login`.")
        with _make_client(token=new_token) as client:
            r = client.request(method, path, **kwargs)
    _raise_for_status(r)
    return r.json()

def post_reset_password_request(email: str) -> dict[str, Any]:
    with _make_client() as client:
        r = client.post("/auth/reset-password/request", json={"email": email})
        _raise_for_status(r)
        return r.json()

def post_reset_password_confirm(email: str, otp: str, new_password: str) -> dict[str, Any]:
    with _make_client() as client:
        r = client.post("/auth/reset-password/confirm", json={
            "email": email,
            "otp": otp,
            "new_password": new_password,
        })
        _raise_for_status(r)
        return r.json()