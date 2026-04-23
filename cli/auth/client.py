import json
import platform
import socket
from collections.abc import Iterator
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
        if isinstance(body.get("errors"), list):
            return "; ".join(f"{e['field']}: {e['message']}" for e in body["errors"])
        if isinstance(body.get("detail"), list):
            return "; ".join(e.get("msg", str(e)) for e in body["detail"])
        return response.text[:300]
    except Exception:
        return response.text[:300]

def _raise_for_status(response: httpx.Response) -> None:
    if response.status_code < 400:
        return
    try:
        response.read()
    except httpx.ResponseNotRead:
        pass
    raise APIError(response.status_code, _extract_detail(response))

def _make_client(
    token: str | None = None,
    extra_headers: dict | None = None,
    timeout: float = 15.0,
) -> httpx.Client:
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    headers.update(_device_headers())
    if extra_headers:
        headers.update(extra_headers)
    return httpx.Client(base_url=_BASE_URL, headers=headers, timeout=timeout)

def post_signup(username: str, email: str, password: str) -> dict[str, Any]:
    with _make_client() as c:
        r = c.post("/auth/signup", json={"username": username, "email": email, "password": password})
        _raise_for_status(r)
        return r.json()

def post_verify_otp(email: str, otp: str) -> dict[str, Any]:
    with _make_client() as c:
        r = c.post("/auth/verify-otp", json={"email": email, "otp": otp})
        _raise_for_status(r)
        return r.json()

def post_resend_otp(email: str) -> dict[str, Any]:
    with _make_client() as c:
        r = c.post("/auth/resend-otp", json={"email": email})
        _raise_for_status(r)
        return r.json()

def post_login(identifier: str, password: str) -> dict[str, Any]:
    with _make_client() as c:
        r = c.post("/auth/login", json={"identifier": identifier, "password": password})
        _raise_for_status(r)
        return r.json()

def post_refresh(refresh_token: str) -> dict[str, Any]:
    with _make_client() as c:
        r = c.post("/auth/refresh", json={"refresh_token": refresh_token})
        _raise_for_status(r)
        return r.json()

def post_logout(refresh_token: str) -> dict[str, Any]:
    with _make_client() as c:
        r = c.post("/auth/logout", json={"refresh_token": refresh_token})
        _raise_for_status(r)
        return r.json()

def get_me() -> dict[str, Any]:
    token = _require_token()
    with _make_client(token=token) as c:
        r = c.get("/auth/me")
    if r.status_code == 401:
        new_token = _silent_refresh()
        if not new_token:
            raise APIError(401, "Session expired. Run `cmdmesh login`.")
        with _make_client(token=new_token) as c:
            r = c.get("/auth/me")
    _raise_for_status(r)
    return r.json()

def post_reset_password_request(email: str) -> dict[str, Any]:
    with _make_client() as c:
        r = c.post("/auth/reset-password/request", json={"email": email})
        _raise_for_status(r)
        return r.json()

def post_reset_password_confirm(email: str, otp: str, new_password: str) -> dict[str, Any]:
    with _make_client() as c:
        r = c.post("/auth/reset-password/confirm", json={
            "email": email, "otp": otp, "new_password": new_password,
        })
        _raise_for_status(r)
        return r.json()

def get_hf_models() -> list[dict[str, Any]]:
    token = _require_token()
    with _make_client(token=token) as c:
        r = c.get("/chat/models")
        _raise_for_status(r)
        return r.json().get("models", [])

def create_chat_session(
    model_id: str,
    system_context: str | None = None,
    title: str = "New chat",
) -> dict[str, Any]:
    token = _require_token()
    with _make_client(token=token) as c:
        r = c.post("/chat/sessions", json={
            "model_id": model_id,
            "system_context": system_context,
            "title": title,
        })
        _raise_for_status(r)
        return r.json()

def list_chat_sessions(limit: int = 20) -> list[dict[str, Any]]:
    token = _require_token()
    with _make_client(token=token) as c:
        r = c.get("/chat/sessions", params={"limit": limit})
        _raise_for_status(r)
        return r.json()

def get_chat_session(session_id: str) -> dict[str, Any]:
    token = _require_token()
    with _make_client(token=token) as c:
        r = c.get(f"/chat/sessions/{session_id}")
        _raise_for_status(r)
        return r.json()

def delete_chat_session(session_id: str) -> None:
    token = _require_token()
    with _make_client(token=token) as c:
        r = c.delete(f"/chat/sessions/{session_id}")
        _raise_for_status(r)

def clear_chat_context(session_id: str) -> None:
    token = _require_token()
    with _make_client(token=token) as c:
        r = c.post(f"/chat/sessions/{session_id}/clear")
        _raise_for_status(r)

def stream_chat_message(
    session_id: str,
    content: str,
    hf_token: str,
) -> Iterator[dict[str, Any]]:
    jwt_token = _require_token()

    def _do_stream(tok: str) -> Iterator[dict[str, Any]]:
        extra = {"X-HF-Token": hf_token}
        with _make_client(token=tok, extra_headers=extra, timeout=120.0) as c:
            with c.stream(
                "POST",
                f"/chat/sessions/{session_id}/message",
                json={"session_id": session_id, "content": content},
            ) as response:
                if response.status_code == 401:
                    raise APIError(401, "Unauthorized")
                if response.status_code >= 400:
                    raise APIError(
                        response.status_code,
                        response.read().decode()[:300],
                    )
                for line in response.iter_lines():
                    line = line.strip()
                    if line:
                        try:
                            yield json.loads(line)
                        except json.JSONDecodeError:
                            continue

    try:
        yield from _do_stream(jwt_token)
    except APIError as exc:
        if exc.status_code == 401:
            new_tok = _silent_refresh()
            if not new_tok:
                raise APIError(401, "Session expired. Run `cmdmesh login`.")
            yield from _do_stream(new_tok)
        else:
            raise

def search_query(query: str, max_results: int = 5) -> dict[str, Any]:
    token = _require_token()
    with _make_client(token=token) as c:
        r = c.post("/search/query", json={"query": query, "max_results": max_results})
        _raise_for_status(r)
        return r.json()

def stream_search(
    query: str,
    ai_question: str,
    extra_headers: dict[str, str]
) -> Iterator[dict[str, Any]]:
    token = _require_token()
    with _make_client(token=token, extra_headers=extra_headers, timeout=60.0) as c:
        with c.stream(
            "POST",
            "/search/query/stream",
            json={"query": query, "ai_question": ai_question}
        ) as r:
            _raise_for_status(r)
            for line in r.iter_lines():
                if line.strip():
                    yield json.loads(line)

def url_context(url: str, max_chars: int = 8000) -> dict[str, Any]:
    token = _require_token()
    with _make_client(token=token) as c:
        r = c.post("/search/url", json={"url": url, "max_chars": max_chars})
        _raise_for_status(r)
        return r.json()

def stream_url_context(
    url: str,
    ai_question: str,
    extra_headers: dict[str, str]
) -> Iterator[dict[str, Any]]:
    token = _require_token()
    with _make_client(token=token, extra_headers=extra_headers, timeout=60.0) as c:
        with c.stream(
            "POST",
            "/search/url/stream",
            json={"url": url, "ai_question": ai_question}
        ) as r:
            _raise_for_status(r)
            for line in r.iter_lines():
                if line.strip():
                    yield json.loads(line)

def _require_token() -> str:
    token = CredentialStore.get_access_token()
    if not token:
        raise APIError(401, "Not logged in. Run `cmdmesh login` first.")
    return token


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

def stream_code_assist(
    content: str,
    task: str,
    language: str | None = None,
    extra_headers: dict | None = None,
) -> Iterator[dict[str, Any]]:
    token = _require_token()

    def _do_stream(tok: str) -> Iterator[dict[str, Any]]:
        payload: dict[str, Any] = {"task": task, "content": content}
        if language:
            payload["language"] = language
        with _make_client(token=tok, extra_headers=extra_headers, timeout=180.0) as c:
            with c.stream("POST", "/code/assist/stream", json=payload) as response:
                if response.status_code == 401:
                    raise APIError(401, "Unauthorized")
                _raise_for_status(response)
                for line in response.iter_lines():
                    if line.strip():
                        try:
                            yield json.loads(line)
                        except json.JSONDecodeError:
                            continue

    try:
        yield from _do_stream(token)
    except APIError as exc:
        if exc.status_code == 401:
            new_tok = _silent_refresh()
            if not new_tok:
                raise APIError(401, "Session expired. Run `cmdmesh login`.")
            yield from _do_stream(new_tok)
        else:
            raise