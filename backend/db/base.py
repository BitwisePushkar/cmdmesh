from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from backend.config import get_settings

class Base(DeclarativeBase):
    pass

def create_engine(database_url: str | None = None):
    url = database_url or get_settings().database_url
    return create_async_engine(
        url,
        echo=False,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )

def create_session_factory(engine=None):
    if engine is None:
        engine = create_engine()
    return async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )

engine = create_engine()
AsyncSessionLocal = create_session_factory(engine)