from __future__ import annotations

import json

from fastapi import APIRouter, Body, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

from ..services.chat import (
    bot_stream,
    build_chat_runtime_config,
    get_session_stop_event,
    release_session_run,
    request_stop,
    try_acquire_session_run,
)
from ..services.execution import execute_code_safe
from ..services.workspace import get_session_workspace, validate_session_id
from ..settings import settings


router = APIRouter()


@router.post("/execute")
async def execute_code_api(request: dict):
    code = request.get("code", "")
    session_id = request.get("session_id", "default")
    workspace_dir = get_session_workspace(session_id)

    if not code:
        return {
            "success": False,
            "result": "Error: No code provided",
            "message": "Code execution failed",
        }

    session_lock = try_acquire_session_run(session_id)
    if session_lock is None:
        raise HTTPException(status_code=409, detail="Session already has an active execution")
    stop_event = get_session_stop_event(session_id)
    stop_event.clear()
    try:
        result = await run_in_threadpool(
            execute_code_safe,
            code,
            workspace_dir,
            session_id,
            None,
            stop_event,
        )
        success = not result.startswith(("[Error]", "[Timeout]", "[Cancelled]"))
        return {
            "success": success,
            "result": result,
            "message": "Code executed successfully" if success else "Code execution failed",
        }
    except Exception as exc:
        return {
            "success": False,
            "result": f"Error: {exc}",
            "message": "Code execution failed",
        }
    finally:
        release_session_run(session_id, session_lock)


@router.post("/chat/completions")
async def chat(body: dict = Body(...)):
    messages = body.get("messages", [])
    workspace = body.get("workspace", [])
    session_id = validate_session_id(body.get("session_id", "default"))
    try:
        runtime_config = build_chat_runtime_config(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    def generate():
        for delta_content in bot_stream(messages, workspace, session_id, runtime_config):
            chunk = {
                "id": "chatcmpl-stream",
                "object": "chat.completion.chunk",
                "created": 1677652288,
                "model": runtime_config.model or settings.model_path,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": delta_content},
                        "finish_reason": None,
                    }
                ],
            }
            yield json.dumps(chunk) + "\n"

        end_chunk = {
            "id": "chatcmpl-stream",
            "object": "chat.completion.chunk",
            "created": 1677652288,
            "model": runtime_config.model or settings.model_path,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }
        yield json.dumps(end_chunk) + "\n"

    return StreamingResponse(generate(), media_type="text/plain")


@router.post("/chat/stop")
async def stop_chat(body: dict = Body(default={})):
    session_id = body.get("session_id", "default")
    request_stop(session_id)
    return {"message": "stop requested", "session_id": session_id}
