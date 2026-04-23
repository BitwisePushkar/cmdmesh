import logging
from typing import Annotated
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import StreamingResponse
import json
import json as _json
import uuid
from backend.dependencies.auth import CurrentUser
from backend.dependencies.db import get_db
from backend.dependencies.redis import get_redis
from backend.schemas.search import (ContextInjectedResponse, SearchQueryRequest,
 SearchQueryResponse, SearchResult, URLContextRequest, URLContextResponse,)
from backend.services.search_service import (SearchError, build_search_context_message,
 search, search_with_ai_answer,)
from backend.services.url_service import (URLBlockedError, URLFetchError,
 build_url_context_message, fetch_and_extract, fetch_with_ai_answer,_build_context_block,)
from backend.services.providers.huggingface import stream_hf_response
from backend.services.search_service import _results_to_context_block
from backend.services.chat_service import ChatService
from sqlalchemy import select
from backend.models.chat import ChatSession
from sqlalchemy.ext.asyncio import AsyncSession
import redis.asyncio as aioredis

log = logging.getLogger(__name__)
router = APIRouter(prefix="/search", tags=["search"])

def _require_hf_token(x_hf_token: str | None) -> str:
    if not x_hf_token or not x_hf_token.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "X-HF-Token header is required for AI-powered search. "
                "Get your free token at https://huggingface.co/settings/tokens"
            ),
        )
    return x_hf_token.strip()

@router.post(
    "/query",
    response_model=SearchQueryResponse,
    summary="DuckDuckGo web search (optionally ask AI about the results)",
)
async def search_query(
    req: SearchQueryRequest,
    current_user: CurrentUser,
    x_hf_token: Annotated[str | None, Header()] = None,
    x_hf_model_id: Annotated[str | None, Header()] = None,
) -> SearchQueryResponse:
    ai_answer: str | None = None

    if req.ai_question:
        hf_token = _require_hf_token(x_hf_token)
        if not x_hf_model_id:
            raise HTTPException(
                status_code=422,
                detail="X-HF-Model-Id header is required when ai_question is set.",
            )
        try:
            results, ai_answer = await search_with_ai_answer(
                query=req.query,
                ai_question=req.ai_question,
                hf_token=hf_token,
                model_id=x_hf_model_id.strip(),
                max_results=req.max_results,
            )
        except SearchError as exc:
            raise HTTPException(status_code=503, detail=str(exc))
    else:
        try:
            results = await search(req.query, max_results=req.max_results)
        except SearchError as exc:
            raise HTTPException(status_code=503, detail=str(exc))

    return SearchQueryResponse(
        query=req.query,
        results=results,
        ai_answer=ai_answer,
        total_found=len(results),
    )


@router.post(
    "/query/stream",
    summary="Search + stream AI answer (newline-delimited JSON)",
)
async def search_query_stream(
    req: SearchQueryRequest,
    current_user: CurrentUser,
    x_hf_token: Annotated[str | None, Header()] = None,
    x_hf_model_id: Annotated[str | None, Header()] = None,
) -> StreamingResponse:
    if not req.ai_question:
        raise HTTPException(
            status_code=422,
            detail="ai_question is required for streaming endpoint.",
        )

    hf_token = _require_hf_token(x_hf_token)
    if not x_hf_model_id:
        raise HTTPException(
            status_code=422,
            detail="X-HF-Model-Id header required.",
        )

    model_id = x_hf_model_id.strip()

    async def event_stream():
        try:
            results = await search(req.query, max_results=req.max_results)
        except SearchError as exc:
            yield json.dumps({"type": "error", "error": str(exc)}) + "\n"
            return

        yield json.dumps({
            "type": "results",
            "data": [r.model_dump() for r in results],
        }) + "\n"

        context = _results_to_context_block(req.query, results)
        messages = [
            {"role": "system", "content": context},
            {"role": "user",   "content": req.ai_question},
        ]

        try:
            async for chunk in stream_hf_response(
                hf_token=hf_token,
                model_id=model_id,
                messages=messages,
            ):
                yield json.dumps({"type": "chunk", "chunk": chunk}) + "\n"
        except Exception as exc:
            yield json.dumps({"type": "error", "error": str(exc)}) + "\n"
            return

        yield json.dumps({"type": "done"}) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")

@router.post(
    "/url",
    response_model=URLContextResponse,
    summary="Fetch a URL and extract readable text (optionally ask AI)",
)
async def url_context(
    req: URLContextRequest,
    current_user: CurrentUser,
    x_hf_token: Annotated[str | None, Header()] = None,
    x_hf_model_id: Annotated[str | None, Header()] = None,
) -> URLContextResponse:
    ai_answer: str | None = None
    warnings: list[str] = []

    try:
        if req.ai_question:
            hf_token = _require_hf_token(x_hf_token)
            if not x_hf_model_id:
                raise HTTPException(
                    status_code=422,
                    detail="X-HF-Model-Id required when ai_question is set.",
                )
            text, title, ai_answer, warnings = await fetch_with_ai_answer(
                url=req.url,
                ai_question=req.ai_question,
                hf_token=hf_token,
                model_id=x_hf_model_id.strip(),
                max_chars=req.max_chars,
            )
        else:
            text, title, warnings = await fetch_and_extract(
                req.url, max_chars=req.max_chars
            )

    except URLBlockedError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except URLFetchError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return URLContextResponse(
        url=req.url,
        title=title,
        extracted_text=text,
        char_count=len(text),
        ai_answer=ai_answer,
        error="; ".join(warnings) if warnings else None,
    )

@router.post(
    "/url/stream",
    summary="Fetch URL + stream AI answer (newline-delimited JSON)",
)
async def url_context_stream(
    req: URLContextRequest,
    current_user: CurrentUser,
    x_hf_token: Annotated[str | None, Header()] = None,
    x_hf_model_id: Annotated[str | None, Header()] = None,
) -> StreamingResponse:
    if not req.ai_question:
        raise HTTPException(
            status_code=422,
            detail="ai_question is required for the streaming endpoint.",
        )

    hf_token = _require_hf_token(x_hf_token)
    if not x_hf_model_id:
        raise HTTPException(status_code=422, detail="X-HF-Model-Id required.")

    model_id = x_hf_model_id.strip()

    async def event_stream():
        try:
            text, title, warnings = await fetch_and_extract(
                req.url, max_chars=req.max_chars
            )
        except URLBlockedError as exc:
            yield json.dumps({"type": "error", "error": str(exc)}) + "\n"
            return
        except URLFetchError as exc:
            yield json.dumps({"type": "error", "error": str(exc)}) + "\n"
            return

        yield json.dumps({
            "type": "meta",
            "url": req.url,
            "title": title,
            "char_count": len(text),
            "warnings": warnings,
        }) + "\n"

        context = _build_context_block(req.url, title, text, question=req.ai_question)
        messages = [
            {"role": "system", "content": context},
            {"role": "user",   "content": req.ai_question},
        ]

        try:
            async for chunk in stream_hf_response(
                hf_token=hf_token,
                model_id=model_id,
                messages=messages,
            ):
                yield json.dumps({"type": "chunk", "chunk": chunk}) + "\n"
        except Exception as exc:
            yield json.dumps({"type": "error", "error": str(exc)}) + "\n"
            return

        yield json.dumps({"type": "done"}) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")

@router.post(
    "/inject-search",
    response_model=ContextInjectedResponse,
    summary="Search and inject results into an existing chat session",
)
async def inject_search_into_session(
    req: SearchQueryRequest,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
) -> ContextInjectedResponse:
    if not req.session_id:
        raise HTTPException(
            status_code=422,
            detail="session_id is required to inject into a chat session.",
        )
    svc = ChatService(db, redis)
    try:
        session_uuid = uuid.UUID(req.session_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid session_id format.")

    session = await svc.get_session(session_uuid, current_user.id)
    if not session:
        raise HTTPException(status_code=404, detail="Chat session not found.")

    try:
        results = await search(req.query, max_results=req.max_results)
    except SearchError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    if not results:
        raise HTTPException(
            status_code=404,
            detail=f"No search results found for: {req.query}",
        )
    context_msg = build_search_context_message(req.query, results)
    context_text = context_msg["content"]
    
    await svc.append_system_message(session_uuid, context_text)
    await db.commit()

    return ContextInjectedResponse(
        session_id=req.session_id,
        message=(
            f"Search results for '{req.query}' injected into your chat session. "
            f"({len(results)} results, {len(context_text):,} chars). "
            "You can now ask questions about these results."
        ),
        context_chars=len(context_text),
    )

@router.post(
    "/inject-url",
    response_model=ContextInjectedResponse,
    summary="Fetch URL and inject content into an existing chat session",
)
async def inject_url_into_session(
    req: URLContextRequest,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
) -> ContextInjectedResponse:
    if not req.session_id:
        raise HTTPException(
            status_code=422,
            detail="session_id is required to inject into a chat session.",
        )
    svc = ChatService(db, redis)
    try:
        session_uuid = uuid.UUID(req.session_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid session_id format.")

    session = await svc.get_session(session_uuid, current_user.id)
    if not session:
        raise HTTPException(status_code=404, detail="Chat session not found.")

    try:
        text, title, warnings = await fetch_and_extract(req.url, max_chars=req.max_chars)
    except URLBlockedError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except URLFetchError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    context_msg = build_url_context_message(req.url, title, text)
    context_text = context_msg["content"]

    await svc.append_system_message(session_uuid, context_text)
    await db.commit()

    label = title or req.url
    return ContextInjectedResponse(
        session_id=req.session_id,
        message=(
            f"Content from '{label}' injected into your chat session "
            f"({len(text):,} chars extracted). "
            "You can now ask questions about this page."
        ),
        context_chars=len(context_text),
    )