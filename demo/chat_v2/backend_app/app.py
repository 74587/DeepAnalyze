from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware

from .routers.chat import router as chat_router
from .routers.code_editing import router as code_editing_router
from .routers.export import router as export_router
from .routers.session import router as session_router
from .routers.workspace import router as workspace_router
from .services.docker_executor import (
    cleanup_idle_containers,
    shutdown_execution_backend,
    validate_execution_backend_configuration,
)

logger = logging.getLogger(__name__)

_REAPER_INTERVAL_SEC = 60


async def _idle_container_reaper() -> None:
    while True:
        await asyncio.sleep(_REAPER_INTERVAL_SEC)
        try:
            await run_in_threadpool(cleanup_idle_containers)
        except Exception as exc:  # pragma: no cover - best-effort reclamation
            logger.warning("idle container reaper failed: %s", exc)


@asynccontextmanager
async def lifespan(_: FastAPI):
    validate_execution_backend_configuration()
    reaper_task = asyncio.create_task(_idle_container_reaper())
    try:
        yield
    finally:
        reaper_task.cancel()
        with suppress(asyncio.CancelledError):
            await reaper_task
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
