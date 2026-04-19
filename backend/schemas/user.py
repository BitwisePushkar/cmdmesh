import uuid
from datetime import datetime
from pydantic import BaseModel, EmailStr

class UserPublic(BaseModel):
    id: uuid.UUID
    username: str
    email: EmailStr
    is_verified: bool
    created_at: datetime
    model_config = {"from_attributes": True}