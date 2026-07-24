from langchain.agents import create_agent
from langchain.agents.middleware import (
    TodoListMiddleware,
    ModelRetryMiddleware,
    ToolCallLimitMiddleware,
)
from langchain.chat_models import init_chat_model
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from .tools.cv import create_tools
from ..config import (
    OPENROUTER_MODEL,
    AGENT_SYSTEM_PROMPT,
)


def build_agent(db: AsyncSession, cv_id: int) -> CompiledStateGraph:
    tools = create_tools(db, cv_id)

    model = init_chat_model(
        f"openrouter:{OPENROUTER_MODEL}",
        temperature=0.3,
        max_tokens=8192,
    )

    return create_agent(
        model=model,
        tools=tools,
        system_prompt=AGENT_SYSTEM_PROMPT,
        middleware=[
            TodoListMiddleware(),
            ModelRetryMiddleware(max_retries=2),
            ToolCallLimitMiddleware(run_limit=15),
        ],
    )
