import json
import asyncio
import uuid
from typing import Callable, AsyncGenerator

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.runnables import RunnableConfig
from sqlalchemy.ext.asyncio import AsyncSession
from langchain_openai import ChatOpenAI

from .state import AgentState
from .agents.react_llm import LLMReActAgent
from .tools.cv import GetCurrentHTMLTool, EditCVTool
from ..config import (
    OPENROUTER_API_KEY, OPENROUTER_BASE_URL, OPENROUTER_MODEL,
    AGENT_SYSTEM_PROMPT, MAX_ITERATIONS,
)

_checkpointer = MemorySaver()


def _create_reasoning_node(agent: LLMReActAgent) -> Callable:
    def reasoning_node(state: AgentState) -> dict:
        return agent.reason(state)
    return reasoning_node


def _create_action_node(agent: LLMReActAgent) -> Callable:
    async def action_node(state: AgentState, config: RunnableConfig) -> dict:
        return await agent.act(state)
    return action_node


def build_graph(agent: LLMReActAgent) -> StateGraph:
    wf = StateGraph(AgentState)
    wf.add_node("reasoning", _create_reasoning_node(agent))
    wf.add_node("action", _create_action_node(agent))
    wf.set_entry_point("reasoning")
    wf.add_conditional_edges("reasoning", lambda s: s.get("next_action", "end"), {
        "action": "action",
        "end": END,
    })
    wf.add_edge("action", "reasoning")
    return wf.compile(checkpointer=_checkpointer)


def _sse_chunk(chat_id: str, content: str | None = None, finish_reason: str | None = None) -> dict:
    delta: dict = {}
    if content is not None:
        delta["content"] = content
    return {
        "id": chat_id,
        "object": "chat.completion.chunk",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }


async def run_agent_stream(
    cv_id: int,
    db: AsyncSession,
    messages: list[dict],
    session_id: str | None = None,
) -> AsyncGenerator[str, None]:
    if session_id is None:
        session_id = str(uuid.uuid4())

    tools = [
        GetCurrentHTMLTool(db, cv_id),
        EditCVTool(db, cv_id),
    ]

    model = ChatOpenAI(
        model=OPENROUTER_MODEL,
        openai_api_key=OPENROUTER_API_KEY,
        base_url=OPENROUTER_BASE_URL,
        temperature=0.3,
        streaming=True,
    )

    agent = LLMReActAgent(
        model=model,
        tools=tools,
        max_iterations=MAX_ITERATIONS,
        system_prompt=AGENT_SYSTEM_PROMPT,
    )

    queue: asyncio.Queue = asyncio.Queue()
    chat_id = f"chatcmpl-{session_id[:8]}"

    def callback(event: str, data: str) -> None:
        queue.put_nowait((event, data))

    agent.set_callback(callback)

    graph = build_graph(agent)
    config = {"configurable": {"thread_id": session_id, "queue": queue}}

    string_messages = _openai_to_strings(messages)
    initial_state: AgentState = {
        "messages": string_messages,
        "cv_id": cv_id,
        "next_action": "",
        "iterations": 0,
    }

    async def run_graph():
        try:
            await graph.ainvoke(initial_state, config)
        except Exception as e:
            queue.put_nowait(("error", str(e)))
        finally:
            queue.put_nowait(("done", ""))

    task = asyncio.create_task(run_graph())
    should_stop = False

    try:
        while not should_stop:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=0.1)
                evt_type = item[0]

                if evt_type == "done":
                    should_stop = True
                    break
                elif evt_type == "error":
                    yield f"data: {json.dumps(_sse_chunk(chat_id, f'\n\nError: {item[1]}', 'stop'))}\n\n"
                    should_stop = True
                    break
                elif evt_type == "token":
                    yield f"data: {json.dumps(_sse_chunk(chat_id, item[1]))}\n\n"
                elif evt_type == "tool_status":
                    tool_name = item[1]
                    if tool_name == "get_current_html":
                        yield f"data: {json.dumps(_sse_chunk(chat_id, '\n📖 Reading current CV...'))}\n\n"
                    elif tool_name == "edit_cv":
                        yield f"data: {json.dumps(_sse_chunk(chat_id, '\n✏️ Updating CV...'))}\n\n"
                    else:
                        yield f"data: {json.dumps(_sse_chunk(chat_id, f'\n🔧 {tool_name}'))}\n\n"
                elif evt_type == "tool_result":
                    yield f"data: {json.dumps(_sse_chunk(chat_id, f'\n{item[1]}'))}\n\n"
                else:
                    yield f"data: {json.dumps(_sse_chunk(chat_id, item[1] if len(item) > 1 else ''))}\n\n"

            except asyncio.TimeoutError:
                if task.done():
                    exc = task.exception()
                    if exc:
                        yield f"data: {json.dumps(_sse_chunk(chat_id, f'\n\nError: {exc}', 'stop'))}\n\n"
                    should_stop = True

        yield "data: [DONE]\n\n"

    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


def _openai_to_strings(openai_messages: list[dict]) -> list[str]:
    result = []
    for msg in openai_messages:
        role = msg.get("role", "")
        content = msg.get("content", "") or ""
        if role == "user":
            result.append(f"User: {content}")
        elif role == "tool":
            result.append(f"Observation: {content}")
        else:
            result.append(f"Assistant: {content}")
    return result
