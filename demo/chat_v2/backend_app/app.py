from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers.chat import router as chat_router
from .routers.code_editing import router as code_editing_router
from .routers.export import router as export_router
from .routers.session import router as session_router
from .routers.workspace import router as workspace_router
from .services.docker_executor import (
    shutdown_execution_backend,
    validate_execution_backend_configuration,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    validate_execution_backend_configuration()
    try:
        yield
    finally:
        shutdown_execution_backend()


def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(workspace_router)
    app.include_router(chat_router)
    app.include_router(code_editing_router)
    app.include_router(export_router)
    app.include_router(session_router)
    return app


app = create_app()
