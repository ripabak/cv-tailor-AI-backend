import json
import asyncio
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from ..auth import get_current_user
from ..database import async_session
from ..models import User, UserCV
from ..services.agent_session_service import start_agent_run, stop_agent_run, stream_events

router = APIRouter(prefix="/api/threads", tags=["agent-protocol"])


@router.post("/{thread_id}/commands")
async def handle_command(
    thread_id: str,
    request: Request,
    user: User = Depends(get_current_user),
):
    command = await request.json()
    method = command.get("method", "")
    cmd_id = command.get("id")

    if method == "run.start":
        params = command.get("params", {})
        input_data = params.get("input") or {}

        if isinstance(input_data, dict):
            cv_id = input_data.get("cv_id")
            messages = input_data.get("messages", [])
        else:
            cv_id = None
            messages = []

        if not cv_id:
            return {
                "type": "error",
                "id": cmd_id,
                "error": "invalid_input",
                "message": "cv_id is required in input",
            }

        async with async_session() as db:
            result = await db.execute(
                select(UserCV.id).where(UserCV.id == cv_id, UserCV.user_id == user.id)
            )
            if not result.scalar_one_or_none():
                return {
                    "type": "error",
                    "id": cmd_id,
                    "error": "not_found",
                    "message": "CV not found or access denied",
                }

        run_id = await start_agent_run(thread_id, cv_id, messages)
        return {
            "type": "success",
            "id": cmd_id,
            "result": {"run_id": run_id},
        }

    if method == "run.cancel":
        stop_agent_run(thread_id)
        return {
            "type": "success",
            "id": cmd_id,
            "result": {"cancelled": True},
        }

    return {
        "type": "error",
        "id": cmd_id,
        "error": "unknown_command",
        "message": f"Unsupported command: {method}",
    }


@router.post("/{thread_id}/stream")
async def handle_stream(
    thread_id: str,
    request: Request,
    user: User = Depends(get_current_user),
):
    params = await request.json()
    channels_str = params.get("channels", "values,lifecycle")
    if isinstance(channels_str, list):
        channel_list = channels_str
    else:
        channel_list = [c.strip() for c in channels_str.split(",") if c.strip()]
    since = params.get("since", 0)

    async def generate():
        async for chunk in stream_events(thread_id, channel_list, since):
            yield chunk

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
