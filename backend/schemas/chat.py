import uuid
from datetime import datetime
from pydantic import BaseModel, Field, field_validator

HF_MODELS: list[dict] = [
    {
        "id":    "meta-llama/Llama-3.1-8B-Instruct",
        "label": "Llama 3.1 8B Instruct",
        "note":  "Meta's highly reliable 8B model — (Gated access required)",
    },
    {
        "id":    "meta-llama/Llama-3.2-1B-Instruct",
        "label": "Llama 3.2 1B Instruct",
        "note":  "Meta's smallest model — Extremely fast and stable",
    },
    {
        "id":    "HuggingFaceH4/zephyr-7b-beta",
        "label": "Zephyr 7B Beta",
        "note":  "A classic stable model — (No gated access required)",
    },
    {
        "id":    "google/gemma-2-2b-it",
        "label": "Gemma 2 2B IT",
        "note":  "Google's smallest Gemma — very well supported",
    },
]

HF_MODEL_IDS: set[str] = {m["id"] for m in HF_MODELS}

class ChatSessionCreateRequest(BaseModel):
    model_id: str = Field(min_length=1, max_length=120)
    system_context: str | None = Field(default=None, max_length=2000)
    title: str = Field(default="New chat", max_length=120)

    @field_validator("model_id")
    @classmethod
    def model_must_be_valid(cls, v: str) -> str:
        # Allow pre-defined models OR any custom repo ID (usually 'owner/repo')
        if v in HF_MODEL_IDS:
            return v
        
        if "/" not in v:
            raise ValueError(
                f"Invalid model ID '{v}'. Must be one of {', '.join(HF_MODEL_IDS)} "
                "or a valid HuggingFace repository ID (e.g. 'owner/model')."
            )
        return v

class ChatMessageRequest(BaseModel):
    session_id: uuid.UUID
    content: str = Field(min_length=1, max_length=32000)

    @field_validator("content")
    @classmethod
    def content_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Message content cannot be blank.")
        return v

class ChatSessionUpdateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=120)
    system_context: str | None = Field(default=None, max_length=2000)

class ChatMessageResponse(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    position: int
    prompt_tokens: int | None
    completion_tokens: int | None
    created_at: datetime
    model_config = {"from_attributes": True}

class ChatSessionResponse(BaseModel):
    id: uuid.UUID
    title: str
    model_id: str
    system_context: str | None
    message_count: int
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}

class ChatSessionDetailResponse(ChatSessionResponse):
    messages: list[ChatMessageResponse]

class ModelListResponse(BaseModel):
    models: list[dict]