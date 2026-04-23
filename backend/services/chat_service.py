import json
import logging
import uuid
from datetime import datetime, timezone
import redis.asyncio as aioredis
from langchain_classic.memory import ConversationBufferWindowMemory
from sqlalchemy import func as sqlfunc
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from backend.config import get_settings
from backend.models.chat import ChatMessage, ChatSession
from backend.schemas.chat import ChatSessionCreateRequest

log = logging.getLogger(__name__)
_WINDOW_K = 20

class ChatService:

    def __init__(self, db: AsyncSession, redis: aioredis.Redis) -> None:
        self._db = db
        self._redis = redis
        self._cfg = get_settings()

    async def create_session(
        self,
        user_id: uuid.UUID,
        req: ChatSessionCreateRequest,
    ) -> ChatSession:
        session = ChatSession(
            user_id=user_id,
            title=req.title,
            model_id=req.model_id,
            system_context=req.system_context,
        )
        self._db.add(session)
        await self._db.flush()

        if req.system_context:
            await self._redis_push(
                session.id,
                {"role": "system", "content": req.system_context},
            )

        await self._redis.hset(
            self._meta_key(session.id),
            mapping={"model_id": req.model_id, "user_id": str(user_id)},
        )
        await self._redis.expire(
            self._meta_key(session.id), self._cfg.chat_session_ttl_seconds
        )

        log.info("Session %s created (model=%s user=%s)", session.id, req.model_id, user_id)
        return session

    async def get_session(
        self, session_id: uuid.UUID, user_id: uuid.UUID
    ) -> ChatSession | None:
        r = await self._db.execute(
            select(ChatSession).where(
                ChatSession.id == session_id,
                ChatSession.user_id == user_id,
            )
        )
        return r.scalar_one_or_none()

    async def list_sessions(
        self, user_id: uuid.UUID, limit: int = 20
    ) -> list[ChatSession]:
        r = await self._db.execute(
            select(ChatSession)
            .where(ChatSession.user_id == user_id)
            .order_by(ChatSession.updated_at.desc())
            .limit(min(limit, 100))
        )
        return list(r.scalars())

    async def get_session_with_messages(
        self, session_id: uuid.UUID, user_id: uuid.UUID
    ) -> ChatSession | None:
        r = await self._db.execute(
            select(ChatSession)
            .options(selectinload(ChatSession.messages))
            .where(
                ChatSession.id == session_id,
                ChatSession.user_id == user_id,
            )
        )
        return r.scalar_one_or_none()

    async def delete_session(
        self, session_id: uuid.UUID, user_id: uuid.UUID
    ) -> bool:
        session = await self.get_session(session_id, user_id)
        if not session:
            return False
        await self._db.delete(session)
        await self._clear_redis(session_id)
        return True

    async def update_title(
        self, session_id: uuid.UUID, user_id: uuid.UUID, title: str
    ) -> None:
        await self._db.execute(
            update(ChatSession)
            .where(ChatSession.id == session_id, ChatSession.user_id == user_id)
            .values(title=title[:120])
        )

    async def build_langchain_memory(
        self, session_id: uuid.UUID
    ) -> ConversationBufferWindowMemory:

        memory = ConversationBufferWindowMemory(
            k=_WINDOW_K,
            return_messages=True,
            memory_key="chat_history",
            human_prefix="user",
            ai_prefix="assistant",
        )

        all_messages = await self._get_messages_from_redis(session_id)

        for msg in all_messages:
            role = msg.get("role")
            content = msg.get("content", "")
            if role == "user":
                memory.chat_memory.add_user_message(content)
            elif role == "assistant":
                memory.chat_memory.add_ai_message(content)

        return memory

    async def get_context_messages(self, session_id: uuid.UUID) -> list[dict]:

        return await self._get_messages_from_redis(session_id)

    async def append_user_message(
        self, session_id: uuid.UUID, content: str
    ) -> ChatMessage:
        position = await self._next_position(session_id)
        msg = ChatMessage(
            session_id=session_id,
            role="user",
            content=content,
            position=position,
        )
        self._db.add(msg)
        await self._db.flush()
        await self._bump_session(session_id)
        await self._redis_push(session_id, {"role": "user", "content": content})
        return msg

    async def append_assistant_message(
        self,
        session_id: uuid.UUID,
        content: str,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
    ) -> ChatMessage:
        position = await self._next_position(session_id)
        msg = ChatMessage(
            session_id=session_id,
            role="assistant",
            content=content,
            position=position,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
        self._db.add(msg)
        await self._db.flush()
        await self._bump_session(session_id)
        await self._redis_push(session_id, {"role": "assistant", "content": content})

        if position == 2:
            session = await self._db.get(ChatSession, session_id)
            if session and session.title == "New chat":
                auto_title = content.strip().replace("\n", " ")[:80]
                if auto_title:
                    session.title = auto_title

        return msg

    async def append_system_message(
        self, session_id: uuid.UUID, content: str
    ) -> ChatMessage:
        """
        Append a system message (e.g. injected context) to the history.
        """
        position = await self._next_position(session_id)
        msg = ChatMessage(
            session_id=session_id,
            role="system",
            content=content,
            position=position,
        )
        self._db.add(msg)
        await self._db.flush()
        await self._bump_session(session_id)
        await self._redis_push(session_id, {"role": "system", "content": content})
        return msg

    async def clear_context(self, session_id: uuid.UUID) -> None:

        await self._redis.delete(self._messages_key(session_id))

        result = await self._db.execute(
            select(ChatSession).where(ChatSession.id == session_id)
        )
        session = result.scalar_one_or_none()
        if session and session.system_context:
            await self._redis_push(
                session_id,
                {"role": "system", "content": session.system_context},
            )

        log.info("Cleared context for session %s (system context preserved)", session_id)

    def _messages_key(self, session_id: uuid.UUID) -> str:
        return f"chat:session:{session_id}:messages"

    def _meta_key(self, session_id: uuid.UUID) -> str:
        return f"chat:session:{session_id}:meta"

    async def _get_messages_from_redis(
        self, session_id: uuid.UUID
    ) -> list[dict]:
        raw = await self._redis.lrange(self._messages_key(session_id), 0, -1)
        if raw:
            return [json.loads(m) for m in raw]

        return await self._reload_from_postgres(session_id)

    async def _redis_push(
        self, session_id: uuid.UUID, message: dict
    ) -> None:
        key = self._messages_key(session_id)
        await self._redis.rpush(key, json.dumps(message, ensure_ascii=False))

        max_msgs = self._cfg.chat_max_context_messages
        length = await self._redis.llen(key)
        if length > max_msgs:

            first_raw = await self._redis.lindex(key, 0)
            if first_raw:
                first = json.loads(first_raw)
                if first.get("role") == "system":

                    pipe = self._redis.pipeline()
                    pipe.lrange(key, length - max_msgs + 1, -1)
                    results = await pipe.execute()
                    trimmed = results[0]
                    await self._redis.delete(key)
                    await self._redis.rpush(key, first_raw, *trimmed)
                else:
                    await self._redis.ltrim(key, length - max_msgs, -1)
            else:
                await self._redis.ltrim(key, length - max_msgs, -1)
        await self._redis.expire(key, self._cfg.chat_session_ttl_seconds)

    async def _reload_from_postgres(
        self, session_id: uuid.UUID
    ) -> list[dict]:

        session_result = await self._db.execute(
            select(ChatSession).where(ChatSession.id == session_id)
        )
        session = session_result.scalar_one_or_none()
        if not session:
            return []

        result = await self._db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.position.desc())
            .limit(self._cfg.chat_max_context_messages)
        )
        messages = list(reversed(result.scalars().all()))

        context_msgs = []
        if session.system_context:
            context_msgs.append({"role": "system", "content": session.system_context})

        for msg in messages:
            # We skip the "permanent" system context if it's already added,
            # but we ALLOW re-injecting other system messages (e.g. search results).
            if msg.role == "system" and msg.content == session.system_context:
                continue
            context_msgs.append({"role": msg.role, "content": msg.content})

        for msg in context_msgs:
            await self._redis_push(session_id, msg)

        log.info("Reloaded %d messages + system context Postgres→Redis for session %s",
                 len(context_msgs), session_id)
        return context_msgs

    async def _clear_redis(self, session_id: uuid.UUID) -> None:
        pipe = self._redis.pipeline()
        pipe.delete(self._messages_key(session_id))
        pipe.delete(self._meta_key(session_id))
        await pipe.execute()

    async def _next_position(self, session_id: uuid.UUID) -> int:
        r = await self._db.execute(
            select(sqlfunc.count(ChatMessage.id))
            .where(ChatMessage.session_id == session_id)
        )
        return r.scalar() or 0

    async def _bump_session(self, session_id: uuid.UUID) -> None:
        await self._db.execute(
            update(ChatSession)
            .where(ChatSession.id == session_id)
            .values(
                message_count=ChatSession.message_count + 1,
                updated_at=datetime.now(timezone.utc),
            )
        )
