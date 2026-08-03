from langchain.agents import create_agent
from langchain.agents.middleware import (
    ContextEditingMiddleware,
    ClearToolUsesEdit,
    SummarizationMiddleware,
)
from langchain.chat_models import init_chat_model
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.store.postgres import AsyncPostgresStore
from sqlalchemy.ext.asyncio import AsyncSession

from .tools.cv import create_tools
from .tools.memory import create_memory_tools
from .memory_store import user_namespace
from ..config import (
    OPENROUTER_MODEL,
    AGENT_SYSTEM_PROMPT,
)

MEMORY_INJECT_LIMIT = 100
MEMORY_INJECT_MAX_CHARS = 4000


async def build_memory_summary(store: AsyncPostgresStore, user_id: int) -> str:
    """Format user memory facts into a compact text block."""
    items = await store.asearch(user_namespace(user_id), limit=MEMORY_INJECT_LIMIT)
    lines = [
        f"- ({value.get('category', '?')}) {value.get('content', '')}"
        for item in items
        if (value := item.value)
    ]

    if not lines:
        return ""

    joined = "\n".join(lines)
    if len(joined) > MEMORY_INJECT_MAX_CHARS:
        joined = joined[:MEMORY_INJECT_MAX_CHARS] + "\n... (terpotong)"
    return f"\n\n## MEMORI USER\nFakta yang diketahui tentang user:\n{joined}"


async def build_agent(
    db: AsyncSession,
    cv_id: int,
    user_id: int,
    checkpointer: AsyncPostgresSaver,
    store: AsyncPostgresStore,
) -> CompiledStateGraph:
    tools = create_tools(db, cv_id) + create_memory_tools(store, user_id)

    memory_summary = await build_memory_summary(store, user_id)
    system_prompt = AGENT_SYSTEM_PROMPT + memory_summary

    model = init_chat_model(
        f"openrouter:{OPENROUTER_MODEL}",
        temperature=0.3,
        max_tokens=8192,
    )

    return create_agent(
        model=model,
        tools=tools,
        system_prompt=system_prompt,
        checkpointer=checkpointer,
        middleware=[
            SummarizationMiddleware(
                model=model,
                trigger=("tokens", 80000),
                keep=("messages", 10),
            ),
            ContextEditingMiddleware(
                edits=[
                    ClearToolUsesEdit(
                        trigger=60000,
                        keep=5,
                        clear_tool_inputs=True,
                    ),
                ],
            ),
        ],
    )
