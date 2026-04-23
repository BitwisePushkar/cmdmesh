import json
import uuid
from unittest.mock import patch
from backend.services.providers.base import to_langchain_messages,  ProviderNotConfiguredError, ProviderError
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from backend.services.providers.huggingface import stream_hf_response
import uuid as uuid_mod
from backend.models.chat import ChatSession, ChatMessage
from backend.services.chat_service import ChatService
from backend.schemas.auth import SignupRequest
from backend.services.auth_service import AuthService
import pytest
from httpx import AsyncClient

VALID_MODEL_ID = "meta-llama/Llama-3.1-8B-Instruct"
HF_HEADER = {"X-HF-Token": "hf_test_token_abc123"}

@pytest.fixture
def auth_headers(auth_tokens):
    return {"Authorization": f"Bearer {auth_tokens['access_token']}"}

async def _make_session(
    client: AsyncClient,
    headers: dict,
    model_id: str = VALID_MODEL_ID,
    system_context: str | None = "You are a helpful assistant.",
    title: str = "Test session",
) -> dict:
    r = await client.post(
        "/chat/sessions",
        json={"model_id": model_id, "system_context": system_context, "title": title},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()

def _mock_hf_stream(*chunks: str):
    async def _gen(**kwargs):
        for chunk in chunks:
            yield chunk
    return _gen

async def _send_message(
    client: AsyncClient,
    session_id: str,
    content: str,
    auth_headers: dict,
    hf_header: dict = None,
    mock_chunks: tuple = ("Test response.",),
) -> list[dict]:
    if hf_header is None:
        hf_header = HF_HEADER
    headers = {**auth_headers, **hf_header}

    with patch(
        "backend.routes.chat.stream_hf_response",
        side_effect=_mock_hf_stream(*mock_chunks),
    ):
        r = await client.post(
            f"/chat/sessions/{session_id}/message",
            json={"session_id": session_id, "content": content},
            headers=headers,
        )
    assert r.status_code == 200, r.text
    return [json.loads(line) for line in r.text.strip().split("\n") if line]

@pytest.mark.asyncio
async def test_models_requires_auth(client: AsyncClient):
    r = await client.get("/chat/models")
    assert r.status_code == 401

@pytest.mark.asyncio
async def test_models_returns_four_hf_models(client: AsyncClient, auth_headers):
    r = await client.get("/chat/models", headers=auth_headers)
    assert r.status_code == 200
    models = r.json()["models"]
    assert len(models) == 4
    for m in models:
        assert "id" in m
        assert "label" in m
        assert "note" in m
        assert "/" in m["id"], f"Model id '{m['id']}' is not a full HF repo ID"

@pytest.mark.asyncio
async def test_models_includes_expected_repos(client: AsyncClient, auth_headers):
    r = await client.get("/chat/models", headers=auth_headers)
    ids = [m["id"] for m in r.json()["models"]]
    assert "meta-llama/Llama-3.1-8B-Instruct" in ids
    assert "meta-llama/Llama-3.2-1B-Instruct" in ids
    assert "HuggingFaceH4/zephyr-7b-beta" in ids
    assert "google/gemma-2-2b-it" in ids

@pytest.mark.asyncio
async def test_create_session_requires_auth(client: AsyncClient):
    r = await client.post("/chat/sessions", json={"model_id": VALID_MODEL_ID})
    assert r.status_code == 401

@pytest.mark.asyncio
async def test_list_sessions_requires_auth(client: AsyncClient):
    assert (await client.get("/chat/sessions")).status_code == 401

@pytest.mark.asyncio
async def test_get_session_requires_auth(client: AsyncClient):
    assert (await client.get(f"/chat/sessions/{uuid.uuid4()}")).status_code == 401

@pytest.mark.asyncio
async def test_send_message_requires_auth(client: AsyncClient):
    fid = str(uuid.uuid4())
    r = await client.post(
        f"/chat/sessions/{fid}/message",
        json={"session_id": fid, "content": "hello"},
        headers=HF_HEADER,
    )
    assert r.status_code == 401

@pytest.mark.asyncio
async def test_delete_session_requires_auth(client: AsyncClient):
    assert (await client.delete(f"/chat/sessions/{uuid.uuid4()}")).status_code == 401

@pytest.mark.asyncio
async def test_clear_context_requires_auth(client: AsyncClient):
    assert (await client.post(f"/chat/sessions/{uuid.uuid4()}/clear")).status_code == 401

@pytest.mark.asyncio
async def test_create_session_success(client: AsyncClient, auth_headers):
    s = await _make_session(client, auth_headers)
    assert s["model_id"] == VALID_MODEL_ID
    assert s["system_context"] == "You are a helpful assistant."
    assert s["message_count"] == 0
    assert s["title"] == "Test session"
    assert "id" in s
    assert "created_at" in s

@pytest.mark.asyncio
async def test_create_session_all_four_models(client: AsyncClient, auth_headers):
    models = [
        "meta-llama/Llama-3.1-8B-Instruct",
        "meta-llama/Llama-3.2-1B-Instruct",
        "HuggingFaceH4/zephyr-7b-beta",
        "google/gemma-2-2b-it",
    ]
    for model_id in models:
        r = await client.post(
            "/chat/sessions",
            json={"model_id": model_id},
            headers=auth_headers,
        )
        assert r.status_code == 201, f"Failed for {model_id}: {r.text}"
        assert r.json()["model_id"] == model_id

@pytest.mark.asyncio
async def test_create_session_invalid_model_rejected(client: AsyncClient, auth_headers):
    r = await client.post(
        "/chat/sessions",
        json={"model_id": "not-a-real-model"},
        headers=auth_headers,
    )
    assert r.status_code == 422

@pytest.mark.asyncio
async def test_create_session_without_context(client: AsyncClient, auth_headers):
    s = await _make_session(client, auth_headers, system_context=None)
    assert s["system_context"] is None

@pytest.mark.asyncio
async def test_list_sessions_only_returns_own(
    client: AsyncClient, auth_headers, db_session
):
    await _make_session(client, auth_headers, title="My session")
    await AuthService.create_verified_user(db_session, SignupRequest(
        username="otherchatter", email="other_chat@example.com", password="Password1"
    ))
    await db_session.commit()
    r2 = await client.post("/auth/login", json={
        "identifier": "otherchatter", "password": "Password1"
    })
    other_headers = {"Authorization": f"Bearer {r2.json()['access_token']}"}
    await _make_session(client, other_headers, title="Their session")

    my = (await client.get("/chat/sessions", headers=auth_headers)).json()
    assert all(s["title"] != "Their session" for s in my)

@pytest.mark.asyncio
async def test_get_other_users_session_is_404(
    client: AsyncClient, auth_headers, db_session
):
    await AuthService.create_verified_user(db_session, SignupRequest(
        username="snooper", email="snoop@example.com", password="Password1"
    ))
    await db_session.commit()
    r2 = await client.post("/auth/login", json={
        "identifier": "snooper", "password": "Password1"
    })
    other_headers = {"Authorization": f"Bearer {r2.json()['access_token']}"}
    other_session = await _make_session(client, other_headers)

    r = await client.get(
        f"/chat/sessions/{other_session['id']}", headers=auth_headers
    )
    assert r.status_code == 404

@pytest.mark.asyncio
async def test_get_session_includes_messages(client: AsyncClient, auth_headers):
    s = await _make_session(client, auth_headers)
    r = await client.get(f"/chat/sessions/{s['id']}", headers=auth_headers)
    assert r.status_code == 200
    assert "messages" in r.json()

@pytest.mark.asyncio
async def test_delete_session(client: AsyncClient, auth_headers):
    s = await _make_session(client, auth_headers)
    assert (await client.delete(f"/chat/sessions/{s['id']}", headers=auth_headers)).status_code == 204
    assert (await client.get(f"/chat/sessions/{s['id']}", headers=auth_headers)).status_code == 404

@pytest.mark.asyncio
async def test_update_session_title(client: AsyncClient, auth_headers):
    s = await _make_session(client, auth_headers)
    r = await client.patch(
        f"/chat/sessions/{s['id']}",
        json={"title": "Renamed session"},
        headers=auth_headers,
    )
    assert r.status_code == 200

@pytest.mark.asyncio
async def test_clear_context(client: AsyncClient, auth_headers):
    s = await _make_session(client, auth_headers)
    r = await client.post(f"/chat/sessions/{s['id']}/clear", headers=auth_headers)
    assert r.status_code == 204

@pytest.mark.asyncio
async def test_message_without_hf_token_rejected(client: AsyncClient, auth_headers):
    s = await _make_session(client, auth_headers)
    r = await client.post(
        f"/chat/sessions/{s['id']}/message",
        json={"session_id": s["id"], "content": "hello"},
        headers=auth_headers, 
    )
    assert r.status_code == 422
    assert "X-HF-Token" in r.json()["detail"]

@pytest.mark.asyncio
async def test_message_with_empty_hf_token_rejected(client: AsyncClient, auth_headers):
    s = await _make_session(client, auth_headers)
    r = await client.post(
        f"/chat/sessions/{s['id']}/message",
        json={"session_id": s["id"], "content": "hello"},
        headers={**auth_headers, "X-HF-Token": "   "},
    )
    assert r.status_code == 422

@pytest.mark.asyncio
async def test_stream_returns_chunks_then_done(client: AsyncClient, auth_headers):
    s = await _make_session(client, auth_headers)
    chunks = await _send_message(
        client, s["id"], "Hello", auth_headers,
        mock_chunks=("Hello", " there", "!")
    )
    text_chunks = [c for c in chunks if c.get("chunk")]
    assert [c["chunk"] for c in text_chunks] == ["Hello", " there", "!"]

    last = chunks[-1]
    assert last["done"] is True
    assert last.get("error") is None
    assert last.get("session_id") == s["id"]

@pytest.mark.asyncio
async def test_stream_persists_user_and_assistant_to_db(
    client: AsyncClient, auth_headers
):
    s = await _make_session(client, auth_headers)
    await _send_message(
        client, s["id"], "What is 2+2?", auth_headers,
        mock_chunks=("The answer is 4.",)
    )

    detail = (await client.get(f"/chat/sessions/{s['id']}", headers=auth_headers)).json()
    messages = detail["messages"]
    roles = [m["role"] for m in messages]
    assert "user" in roles
    assert "assistant" in roles

    user_msg = next(m for m in messages if m["role"] == "user")
    assert user_msg["content"] == "What is 2+2?"

    ai_msg = next(m for m in messages if m["role"] == "assistant")
    assert ai_msg["content"] == "The answer is 4."

@pytest.mark.asyncio
async def test_empty_message_content_rejected(client: AsyncClient, auth_headers):
    s = await _make_session(client, auth_headers)
    r = await client.post(
        f"/chat/sessions/{s['id']}/message",
        json={"session_id": s["id"], "content": ""},
        headers={**auth_headers, **HF_HEADER},
    )
    assert r.status_code == 422

@pytest.mark.asyncio
async def test_whitespace_only_message_rejected(client: AsyncClient, auth_headers):
    s = await _make_session(client, auth_headers)
    r = await client.post(
        f"/chat/sessions/{s['id']}/message",
        json={"session_id": s["id"], "content": "   \n   "},
        headers={**auth_headers, **HF_HEADER},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_provider_error_returned_in_stream(client: AsyncClient, auth_headers):
    s = await _make_session(client, auth_headers)

    async def _bad_stream(**kwargs):
        raise ProviderError("HF API quota exceeded")
        yield

    with patch(
        "backend.routes.chat.stream_hf_response",
        side_effect=_bad_stream,
    ):
        r = await client.post(
            f"/chat/sessions/{s['id']}/message",
            json={"session_id": s["id"], "content": "hi"},
            headers={**auth_headers, **HF_HEADER},
        )

    assert r.status_code == 200
    last = json.loads(r.text.strip().split("\n")[-1])
    assert last["done"] is True
    assert last["error"] is not None
    assert "quota" in last["error"].lower()

@pytest.mark.asyncio
async def test_provider_not_configured_error_in_stream(client: AsyncClient, auth_headers):
    s = await _make_session(client, auth_headers)
    async def _no_token(**kwargs):
        raise ProviderNotConfiguredError("HuggingFace API token is required")
        yield
    with patch(
        "backend.routes.chat.stream_hf_response",
        side_effect=_no_token,
    ):
        r = await client.post(
            f"/chat/sessions/{s['id']}/message",
            json={"session_id": s["id"], "content": "hi"},
            headers={**auth_headers, **HF_HEADER},
        )

    last = json.loads(r.text.strip().split("\n")[-1])
    assert last["done"] is True
    assert "token" in last["error"].lower()

@pytest.mark.asyncio
async def test_message_count_increments_after_exchange(client: AsyncClient, auth_headers):
    s = await _make_session(client, auth_headers)
    assert s["message_count"] == 0
    await _send_message(client, s["id"], "Hi", auth_headers)
    updated = (await client.get(f"/chat/sessions/{s['id']}", headers=auth_headers)).json()
    assert updated["message_count"] == 2

@pytest.mark.asyncio
async def test_second_turn_includes_full_context(client: AsyncClient, auth_headers):
    s = await _make_session(client, auth_headers, system_context="Be concise.")
    captured: list[list[dict]] = []

    async def _capture(**kwargs):
        captured.append(list(kwargs["messages"]))
        yield "ok"

    with patch("backend.routes.chat.stream_hf_response", side_effect=_capture):
        await client.post(
            f"/chat/sessions/{s['id']}/message",
            json={"session_id": s['id'], "content": "First question"},
            headers={**auth_headers, **HF_HEADER},
        )

    with patch("backend.routes.chat.stream_hf_response", side_effect=_capture):
        await client.post(
            f"/chat/sessions/{s['id']}/message",
            json={"session_id": s['id'], "content": "Second question"},
            headers={**auth_headers, **HF_HEADER},
        )

    assert captured[0][0]["role"] == "system"
    assert captured[0][-1]["content"] == "First question"
    roles_turn2 = [m["role"] for m in captured[1]]
    assert roles_turn2[0] == "system"
    assert "user" in roles_turn2
    assert "assistant" in roles_turn2
    assert captured[1][-1]["content"] == "Second question"

@pytest.mark.asyncio
async def test_clear_context_reseeds_system_message(
    client: AsyncClient, auth_headers, redis_client
):
    s = await _make_session(client, auth_headers, system_context="Be a pirate.")
    await _send_message(client, s["id"], "Hello", auth_headers)
    await client.post(f"/chat/sessions/{s['id']}/clear", headers=auth_headers)
    raw = await redis_client.lrange(f"chat:session:{s['id']}:messages", 0, -1)
    messages = [json.loads(m) for m in raw]
    roles = [m["role"] for m in messages]
    assert "system" in roles
    assert "user" not in roles
    assert "assistant" not in roles

@pytest.mark.asyncio
async def test_langchain_memory_built_from_redis(redis_client, db_session):
    svc = ChatService(db_session, redis_client)
    session_id = uuid.uuid4()
    raw_messages = [
        json.dumps({"role": "system", "content": "You are a pirate."}),
        json.dumps({"role": "user", "content": "Hello!"}),
        json.dumps({"role": "assistant", "content": "Ahoy matey!"}),
    ]
    await redis_client.rpush(
        f"chat:session:{session_id}:messages", *raw_messages
    )
    await redis_client.expire(f"chat:session:{session_id}:messages", 3600)
    memory = await svc.build_langchain_memory(session_id)
    lc_messages = memory.chat_memory.messages
    assert len(lc_messages) == 2
    assert lc_messages[0].content == "Hello!"
    assert lc_messages[1].content == "Ahoy matey!"

@pytest.mark.asyncio
async def test_langchain_memory_reloads_from_postgres_on_redis_miss(
    db_session, redis_client, verified_user
):
    session_id = uuid_mod.uuid4()
    session = ChatSession(
        id=session_id,
        user_id=verified_user.id,
        model_id=VALID_MODEL_ID,
        title="Test",
        message_count=2,
    )
    db_session.add(session)
    db_session.add(ChatMessage(
        session_id=session_id, role="user",
        content="Restored user msg", position=0,
    ))
    db_session.add(ChatMessage(
        session_id=session_id, role="assistant",
        content="Restored AI msg", position=1,
    ))
    await db_session.commit()
    svc = ChatService(db_session, redis_client)
    messages = await svc.get_context_messages(session_id)
    assert len(messages) == 2
    assert messages[0]["content"] == "Restored user msg"
    assert messages[1]["content"] == "Restored AI msg"
    raw = await redis_client.lrange(f"chat:session:{session_id}:messages", 0, -1)
    assert len(raw) == 2

@pytest.mark.asyncio
async def test_stream_hf_response_raises_when_token_empty():
    with pytest.raises(ProviderNotConfiguredError):
        async for _ in stream_hf_response(
            hf_token="",
            model_id=VALID_MODEL_ID,
            messages=[{"role": "user", "content": "hi"}],
        ):
            pass

@pytest.mark.asyncio
async def test_stream_hf_response_raises_for_whitespace_token():
    with pytest.raises(ProviderNotConfiguredError):
        async for _ in stream_hf_response(
            hf_token="   ",
            model_id=VALID_MODEL_ID,
            messages=[{"role": "user", "content": "hi"}],
        ):
            pass

def test_to_langchain_messages_all_roles():
    msgs = [
        {"role": "system",    "content": "You are an expert."},
        {"role": "user",      "content": "What is Python?"},
        {"role": "assistant", "content": "Python is a language."},
        {"role": "user",      "content": "Tell me more."},
    ]
    result = to_langchain_messages(msgs)
    assert len(result) == 4
    assert isinstance(result[0], SystemMessage)
    assert isinstance(result[1], HumanMessage)
    assert isinstance(result[2], AIMessage)
    assert isinstance(result[3], HumanMessage)
    assert result[0].content == "You are an expert."
    assert result[2].content == "Python is a language."

def test_to_langchain_messages_unknown_role_treated_as_human():
    msgs = [{"role": "tool", "content": "some tool output"}]
    result = to_langchain_messages(msgs)
    assert isinstance(result[0], HumanMessage)

def test_to_langchain_messages_empty_list():
    from backend.services.providers.base import to_langchain_messages
    assert to_langchain_messages([]) == []