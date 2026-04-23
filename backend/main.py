import logging
import sys
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from backend.config import get_settings
from backend.db.base import Base, engine
from backend.routes import auth, chat, search
import backend.models

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    if not settings.token_encryption_key:
        log.critical("TOKEN_ENCRYPTION_KEY is not set. Refusing to start.")
        sys.exit(1)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    log.info("Database tables ready.")
    log.info("cmdmesh backend started — env=%s", settings.app_env)
    yield
    log.info("cmdmesh backend shutting down.")
    await engine.dispose()

def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="cmdmesh API",
        version="0.1.0",
        description="Backend for the cmdmesh CLI tool",
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        lifespan=lifespan,
    )
    app.include_router(auth.router)
    app.include_router(chat.router)
    app.include_router(search.router)
    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = [
            {"field": ".".join(str(l) for l in e["loc"][1:]), "message": e["msg"]}
            for e in exc.errors()
        ]
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": "Validation error", "errors": errors},
        )
    @app.get("/health", tags=["meta"], include_in_schema=False)
    async def health() -> dict:
        return {"status": "ok"}
    return app

app = create_app()