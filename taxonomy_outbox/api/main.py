"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from ..config import Settings
from ..db import make_engine, make_session_factory
from ..relay import OutboxRelay, build_publisher
from ..services.errors import (
    DictionaryNotFound,
    DuplicateTagCode,
    InvalidMerge,
    InvalidTagTransition,
    TagNotFound,
    TagVersionConflict,
)
from .routes import router


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)
    publisher = build_publisher(settings)
    relay = OutboxRelay(
        session_factory,
        publisher,
        batch_size=settings.outbox_batch_size,
        max_attempts=settings.outbox_max_attempts,
        retry_backoff_seconds=settings.outbox_retry_backoff_seconds,
    )

    app = FastAPI(
        title="Member Space Platform - Dictionary & Tag Center outbox",
        version="1.0.0",
        description="Publishes taxonomy tag lifecycle events through a transactional outbox.",
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.publisher = publisher
    app.state.relay = relay
    app.include_router(router)

    @app.get("/healthz", tags=["ops"])
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    _register_error_handlers(app)
    return app


def _register_error_handlers(app: FastAPI) -> None:
    def handler(status_code: int, error: str, message: str | None = None) -> JSONResponse:
        content = {"error": error}
        if message:
            content["detail"] = message
        return JSONResponse(status_code=status_code, content=content)

    @app.exception_handler(TagNotFound)
    async def _tag_not_found(request: Request, exc: TagNotFound) -> JSONResponse:
        return handler(404, "tag_not_found", str(exc))

    @app.exception_handler(DictionaryNotFound)
    async def _dictionary_not_found(request: Request, exc: DictionaryNotFound) -> JSONResponse:
        return handler(404, "dictionary_not_found", str(exc))

    @app.exception_handler(InvalidTagTransition)
    async def _invalid_transition(request: Request, exc: InvalidTagTransition) -> JSONResponse:
        return handler(409, "invalid_tag_transition", str(exc))

    @app.exception_handler(TagVersionConflict)
    async def _version_conflict(request: Request, exc: TagVersionConflict) -> JSONResponse:
        return handler(409, "tag_version_conflict", str(exc))

    @app.exception_handler(InvalidMerge)
    async def _invalid_merge(request: Request, exc: InvalidMerge) -> JSONResponse:
        return handler(409, "invalid_merge", str(exc))

    @app.exception_handler(DuplicateTagCode)
    async def _duplicate_code(request: Request, exc: DuplicateTagCode) -> JSONResponse:
        return handler(409, "duplicate_tag_code", str(exc))

    @app.exception_handler(IntegrityError)
    async def _integrity_error(request: Request, exc: IntegrityError) -> JSONResponse:
        return handler(409, "constraint_violation", "the change violates a database constraint")

    @app.exception_handler(ValueError)
    async def _value_error(request: Request, exc: ValueError) -> JSONResponse:
        return handler(422, "invalid_request", str(exc))


app = create_app()
