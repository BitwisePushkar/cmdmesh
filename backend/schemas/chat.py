import uuid
from datetime import datetime
from pydantic import BaseModel, Field, field_validator

HF_MODELS: list[dict] = [
    {
        "id":    "mistralai/Mistral-7B-Instruct-v0.3",
        "label": "Mistral 7B Instruct",
        "note":  "Fast, strong at reasoning and instruction following",
    },
    {
        "id":    "meta-llama/Meta-Llama-3-8B-Instruct",
        "label": "Llama 3 8B Instruct",
        "note":  "Meta's Llama 3, excellent general quality",
    },
    {
        "id":    "microsoft/Phi-3-mini-4k-instruct",
        "label": "Phi-3 Mini 4K",
        "note":  "Microsoft, very fast and efficient",
    },
    {
        "id":    "HuggingFaceH4/zephyr-7b-beta",
        "label": "Zephyr 7B Beta",
        "note":  "Chat-optimised, good at following complex prompts",
    },
]

HF_MODEL_IDS: set[str] = {m["id"] for m in HF_MODELS}

class ChatSessionCreateRequest(BaseModel):
    model_id: str = Field(min_length=1, max_length=120)
    system_context: str | None = Field(default=None, max_length=2000)
    title: str = Field(default="New chat", max_length=120)

    @field_validator("model_id")
    @classmethod
    def model_must_be_known(cls, v: str) -> str:
        if v not in HF_MODEL_IDS:
            raise ValueError(
                f"Unknown model '{v}'. "
                f"Allowed: {', '.join(HF_MODEL_IDS)}"
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