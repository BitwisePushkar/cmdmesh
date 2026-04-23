import json
import logging
from typing import Annotated
from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import StreamingResponse
from backend.dependencies.auth import CurrentUser
from backend.schemas.code import (CodeAssistRequest, CodeAssistResponse, CodeTask, TASK_LABELS,)
from backend.services.code_service import build_messages
from backend.services.providers import (ProviderError, ProviderNotConfiguredError, stream_hf_response,)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/code", tags=["code"])

def _require_hf_headers(
    x_hf_token: str | None,
    x_hf_model_id: str | None,
) -> tuple[str, str]:
    if not x_hf_token or not x_hf_token.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "X-HF-Token header is required. "
                "Get your free token at https://huggingface.co/settings/tokens"
            ),
        )
    if not x_hf_model_id or not x_hf_model_id.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="X-HF-Model-Id header is required.",
        )
    return x_hf_token.strip(), x_hf_model_id.strip()

@router.get(
    "/tasks",
    summary="List available code assistant tasks",
)
async def list_tasks(_: CurrentUser) -> dict:
    return {
        "tasks": [
            {"id": task.value, "label": label}
            for task, label in TASK_LABELS.items()
        ]
    }

@router.post(
    "/assist",
    response_model=CodeAssistResponse,
    summary="Run a code task and return full response",
)
async def code_assist(
    req: CodeAssistRequest,
    current_user: CurrentUser,
    x_hf_token: Annotated[str | None, Header()] = None,
    x_hf_model_id: Annotated[str | None, Header()] = None,
) -> CodeAssistResponse:
    hf_token, model_id = _require_hf_headers(x_hf_token, x_hf_model_id)
    messages = build_messages(req)

    chunks: list[str] = []
    try:
        async for chunk in stream_hf_response(
            hf_token=hf_token,
            model_id=model_id,
            messages=messages,
        ):
            chunks.append(chunk)
    except ProviderNotConfiguredError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except ProviderError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    result = "".join(chunks)
    return CodeAssistResponse(
        task=req.task,
        language=req.language,
        result=result,
        model_id=model_id,
        char_count_in=len(req.content),
        char_count_out=len(result),
    )

@router.post(
    "/assist/stream",
    summary="Stream a code task response chunk by chunk",
)
async def code_assist_stream(
    req: CodeAssistRequest,
    current_user: CurrentUser,
    x_hf_token: Annotated[str | None, Header()] = None,
    x_hf_model_id: Annotated[str | None, Header()] = None,
) -> StreamingResponse:
    hf_token, model_id = _require_hf_headers(x_hf_token, x_hf_model_id)
    messages = build_messages(req)

    async def event_stream():
        yield json.dumps({
            "type": "meta",
            "task": req.task.value,
            "language": req.language,
            "model_id": model_id,
        }) + "\n"

        total_out = 0
        try:
            async for chunk in stream_hf_response(
                hf_token=hf_token,
                model_id=model_id,
                messages=messages,
            ):
                total_out += len(chunk)
                yield json.dumps({"type": "chunk", "chunk": chunk}) + "\n"

            yield json.dumps({
                "type": "done",
                "char_count_in": len(req.content),
                "char_count_out": total_out,
            }) + "\n"

        except ProviderNotConfiguredError as exc:
            log.warning("HF token issue: %s", exc)
            yield json.dumps({"type": "error", "error": str(exc)}) + "\n"
        except ProviderError as exc:
            log.error("Provider error during code assist: %s", exc)
            yield json.dumps({"type": "error", "error": str(exc)}) + "\n"
        except Exception as exc:
            log.error("Unexpected error in code assist stream: %s", exc, exc_info=True)
            yield json.dumps({
                "type": "error",
                "error": "An unexpected error occurred. Please try again.",
            }) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")