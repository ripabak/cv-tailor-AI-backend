from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ..database import get_db
from ..models import User, UserCV, Conversation, Message as MessageModel
from ..schemas import ChatRequest, MessageResponse
from ..auth import get_current_user
from ..agent.graph import run_agent_stream
from ..services.chat_service import get_or_create_conversation, save_messages
from sqlalchemy import select

router = APIRouter(prefix="/api/cv", tags=["chat"])


@router.post("/{cv_id}/chat")
async def chat_stream(
    cv_id: int,
    request: ChatRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cv_result = await db.execute(
        select(UserCV).where(UserCV.id == cv_id, UserCV.user_id == user.id)
    )
    cv = cv_result.scalar_one_or_none()
    if not cv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CV not found")

    messages = [m.model_dump(exclude_none=True) for m in request.messages]

    conv, is_new = await get_or_create_conversation(db, user.id, cv_id, request.session_id)
    session_id = conv.session_id

    if messages:
        await save_messages(db, conv.id, messages)

    async def generate():
        async for chunk in run_agent_stream(cv_id, db, messages, session_id):
            yield chunk

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Session-Id": session_id,
        },
    )


@router.get("/{cv_id}/messages", response_model=list[MessageResponse])
async def get_messages(
    cv_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cv_result = await db.execute(
        select(UserCV).where(UserCV.id == cv_id, UserCV.user_id == user.id)
    )
    cv = cv_result.scalar_one_or_none()
    if not cv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CV not found")

    conv_result = await db.execute(
        select(Conversation)
        .options(selectinload(Conversation.messages))
        .where(Conversation.cv_id == cv_id, Conversation.user_id == user.id)
        .order_by(Conversation.created_at.desc())
        .limit(1)
    )
    conv = conv_result.scalar_one_or_none()
    if not conv:
        return []

    return [MessageResponse.model_validate(m) for m in conv.messages]


@router.delete("/{cv_id}/chat", status_code=status.HTTP_204_NO_CONTENT)
async def clear_messages(
    cv_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cv_result = await db.execute(
        select(UserCV).where(UserCV.id == cv_id, UserCV.user_id == user.id)
    )
    cv = cv_result.scalar_one_or_none()
    if not cv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CV not found")

    conv_result = await db.execute(
        select(Conversation)
        .where(Conversation.cv_id == cv_id, Conversation.user_id == user.id)
    )
    conversations = conv_result.scalars().all()
    for conv in conversations:
        await db.delete(conv)
    await db.commit()
