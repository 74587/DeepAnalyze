from __future__ import annotations

from fastapi import APIRouter, Body, Query

from ..services.session_state import (
    load_session_state,
    replace_messages,
    update_task_config,
)


router = APIRouter()


@router.get("/session/state")
async def get_session_state(session_id: str = Query("default")):
    return load_session_state(session_id)


@router.put("/session/messages")
async def put_session_messages(body: dict = Body(...)):
    return replace_messages(
        body.get("session_id", "default"),
        body.get("messages") or [],
    )


@router.put("/session/task")
async def put_session_task(body: dict = Body(...)):
    return update_task_config(
        body.get("session_id", "default"),
        body.get("task_config") or {},
    )
