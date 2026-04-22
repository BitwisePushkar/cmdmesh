import json
import logging
import uuid
from typing import Annotated
from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
import redis.asyncio as aioredis
from backend.dependencies.auth import CurrentUser
from backend.dependencies.db import get_db
from backend.dependencies.redis import get_redis
from backend.schemas.chat import (ChatMessageRequest, ChatSessionCreateRequest,
    ChatSessionDetailResponse, ChatSessionResponse, ChatSessionUpdateRequest, HF_MODELS,
    ModelListResponse,)
from backend.services.chat_service import ChatService
from backend.services.providers import (ProviderError, ProviderNotConfiguredError,
 stream_hf_response,)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["chat"])

@router.get(
    "/models",
    response_model=ModelListResponse,
    summary="List available HuggingFace models",
)
async def list_models(_: CurrentUser,) -> ModelListResponse:
    return ModelListResponse(models=HF_MODELS)

@router.post(
    "/sessions",
    response_model=ChatSessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start a new chat session",
)
async def create_session(
    req: ChatSessionCreateRequest,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
) -> ChatSessionResponse:
    svc = ChatService(db, redis)
    session = await svc.create_session(current_user.id, req)
    await db.commit()
    return ChatSessionResponse.model_validate(session)

@router.get(
    "/sessions",
    response_model=list[ChatSessionResponse],
    summary="List my chat sessions",
)
async def list_sessions(
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
    limit: int = 20,
) -> list[ChatSessionResponse]:
    svc = ChatService(db, redis)
    sessions = await svc.list_sessions(current_user.id, limit=limit)
    return [ChatSessionResponse.model_validate(s) for s in sessions]

@router.get(
    "/sessions/{session_id}",
    response_model=ChatSessionDetailResponse,
    summary="Get session with full message history",
)
async def get_session(
    session_id: uuid.UUID,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
) -> ChatSessionDetailResponse:
    svc = ChatService(db, redis)
    session = await svc.get_session_with_messages(session_id, current_user.id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    return ChatSessionDetailResponse.model_validate(session)

@router.patch(
    "/sessions/{session_id}",
    response_model=ChatSessionResponse,
    summary="Update session title",
)
async def update_session(
    session_id: uuid.UUID,
    req: ChatSessionUpdateRequest,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
) -> ChatSessionResponse:
    svc = ChatService(db, redis)
    session = await svc.get_session(session_id, current_user.id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    if req.title:
        await svc.update_title(session_id, current_user.id, req.title)
    await db.commit()
    session = await svc.get_session(session_id, current_user.id)
    return ChatSessionResponse.model_validate(session)

@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete session and all its messages",
)
async def delete_session(
    session_id: uuid.UUID,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
) -> None:
    svc = ChatService(db, redis)
    if not await svc.delete_session(session_id, current_user.id):
        raise HTTPException(status_code=404, detail="Session not found.")
    await db.commit()

@router.post(
    "/sessions/{session_id}/clear",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Clear Redis context window (keeps Postgres history)",
)
async def clear_context(
    session_id: uuid.UUID,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
) -> None:
    svc = ChatService(db, redis)
    if not await svc.get_session(session_id, current_user.id):
        raise HTTPException(status_code=404, detail="Session not found.")
    await svc.clear_context(session_id)
    await db.commit()

@router.post(
    "/sessions/{session_id}/message",
    summary="Send a message and stream the AI response",
    description=(
        "Requires X-HF-Token header with the user's HuggingFace API token. "
        "The token is used for this request only and is never stored."
    ),
)
async def send_message(
    session_id: uuid.UUID,
    req: ChatMessageRequest,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],

    x_hf_token: Annotated[str | None, Header()] = None,
) -> StreamingResponse:
    svc = ChatService(db, redis)
    session = await svc.get_session(session_id, current_user.id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    if not x_hf_token or not x_hf_token.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "X-HF-Token header is required. "
                "Get your free token at https://huggingface.co/settings/tokens"
            ),
        )

    hf_token = x_hf_token.strip()

    await svc.append_user_message(session_id, req.content)

    await svc.build_langchain_memory(session_id)

    messages = await svc.get_context_messages(session_id)

    async def event_stream():
        full_response: list[str] = []
        try:
            async for chunk in stream_hf_response(
                hf_token=hf_token,
                model_id=session.model_id,
                messages=messages,
            ):
                full_response.append(chunk)
                yield json.dumps({"chunk": chunk, "done": False}, ensure_ascii=False) + "\n"

            complete = "".join(full_response)
            if complete:
                await svc.append_assistant_message(session_id, complete)
                await db.commit()

            yield json.dumps({
                "chunk": "",
                "done": True,
                "session_id": str(session_id),
            }) + "\n"

        except ProviderNotConfiguredError as exc:
            log.warning("HF token missing/invalid: %s", exc)
            yield json.dumps({"chunk": "", "done": True, "error": str(exc)}) + "\n"

        except ProviderError as exc:
            log.error("HF provider error: %s", exc)
            yield json.dumps({"chunk": "", "done": True, "error": str(exc)}) + "\n"

        except Exception as exc:
            log.error("Unexpected stream error: %s", exc, exc_info=True)
            yield json.dumps({
                "chunk": "",
                "done": True,
                "error": "An unexpected error occurred. Please try again.",
            }) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")
