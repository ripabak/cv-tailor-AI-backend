import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ..models import Conversation, Message


async def get_or_create_conversation(
    db: AsyncSession,
    user_id: int,
    cv_id: int,
    session_id: str | None,
) -> tuple[Conversation, bool]:
    if session_id:
        result = await db.execute(
            select(Conversation)
            .options(selectinload(Conversation.messages))
            .where(Conversation.session_id == session_id)
        )
        conv = result.scalar_one_or_none()
        if conv:
            return conv, False

    new_session_id = session_id or str(uuid.uuid4())
    conv = Conversation(
        session_id=new_session_id,
        user_id=user_id,
        cv_id=cv_id,
    )
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return conv, True


async def save_messages(
    db: AsyncSession,
    conversation_id: int,
    messages: list[dict],
) -> None:
    from sqlalchemy import delete as sa_delete
    from ..models import Message as MessageModel

    await db.execute(
        sa_delete(MessageModel).where(MessageModel.conversation_id == conversation_id)
    )

    for msg in messages:
        db_msg = MessageModel(
            conversation_id=conversation_id,
            role=msg.get("role", "user"),
            content=msg.get("content"),
            tool_calls=msg.get("tool_calls"),
            tool_call_id=msg.get("tool_call_id"),
        )
        db.add(db_msg)
    await db.commit()
