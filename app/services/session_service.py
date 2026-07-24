import json
import asyncio
import uuid
from collections import defaultdict
from typing import AsyncGenerator

from ..agent.agent import build_agent
from ..database import async_session


class AgentSession:
    def __init__(self):
        self.run_id: str | None = None
        self.events: list[dict] = []
        self.subscribers: list[asyncio.Queue] = []
        self._running = False
        self._task: asyncio.Task | None = None
        self._seq = 0

    def buffer_event(self, event: dict):
        self._seq += 1
        event["seq"] = self._seq
        if "event_id" not in event:
            event["event_id"] = str(uuid.uuid4())
        self.events.append(event)
        for q in self.subscribers:
            q.put_nowait(event)

    def subscribe(self) -> asyncio.Queue:
        q = asyncio.Queue()
        self.subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        if q in self.subscribers:
            self.subscribers.remove(q)

    def get_events_since(self, since: int, channels: list[str]) -> list[dict]:
        if since < 0:
            since = 0
        result = []
        for event in self.events:
            seq = event.get("seq", 0)
            method = event.get("method", "")
            if seq > since and (method in channels or "*" in channels):
                result.append(event)
        return result


class SessionManager:
    def __init__(self):
        self._sessions: dict[str, AgentSession] = defaultdict(AgentSession)

    def get(self, thread_id: str) -> AgentSession:
        return self._sessions[thread_id]

    def remove(self, thread_id: str):
        self._sessions.pop(thread_id, None)


session_manager = SessionManager()


def _make_event(method: str, data, namespace: list[str] | None = None) -> dict:
    return {
        "method": method,
        "params": {
            "namespace": namespace or [],
            "data": data,
        },
    }


async def start_agent_run(
    thread_id: str,
    cv_id: int,
    messages: list[dict],
) -> str:
    session = session_manager.get(thread_id)
    run_id = str(uuid.uuid4())
    session.run_id = run_id
    session._running = True
    session.events.clear()

    async def run():
        db = async_session()
        try:
            agent = build_agent(db, cv_id)

            stream = await agent.astream_events(
                {"messages": messages},
                version="v3",
            )

            session.buffer_event(_make_event("lifecycle", {"event": "running", "graph_name": "cv_agent"}))

            pending_tool_ids: list[str] = []

            async for message in stream.messages:
                # Tools from previous round have finished (model is responding)
                for tc_id in pending_tool_ids:
                    session.buffer_event(_make_event("tool_end", {
                        "tool_call_id": tc_id,
                        "output": "",
                        "error": None,
                    }))
                pending_tool_ids.clear()

                msg_id = str(uuid.uuid4())
                node = getattr(message, "node", "agent")

                session.buffer_event(_make_event("message_start", {"id": msg_id, "node": node}))

                if hasattr(message, "reasoning"):
                    async for delta in message.reasoning:
                        session.buffer_event(_make_event("text_delta", {
                            "id": msg_id, "delta": delta, "kind": "reasoning",
                        }))

                if hasattr(message, "text"):
                    async for delta in message.text:
                        session.buffer_event(_make_event("text_delta", {
                            "id": msg_id, "delta": delta, "kind": "text",
                        }))

                if hasattr(message, "tool_calls"):
                    finalized = await message.tool_calls
                    if finalized:
                        tcs = [
                            {
                                "id": tc.get("id", str(uuid.uuid4())),
                                "name": tc["name"],
                                "args": tc["args"],
                                "type": "tool_call",
                            }
                            for tc in finalized
                        ] if isinstance(finalized, list) else []
                        session.buffer_event(_make_event("tool_calls_done", {
                            "id": msg_id,
                            "tool_calls": tcs,
                        }))
                        for tc in tcs:
                            pending_tool_ids.append(tc["id"])
                            session.buffer_event(_make_event("tool_start", {
                                "tool_call_id": tc["id"],
                                "name": tc["name"],
                                "args": tc["args"],
                            }))

                session.buffer_event(_make_event("message_end", {"id": msg_id}))

            # Emit tool_end for any tools left pending at run end
            for tc_id in pending_tool_ids:
                session.buffer_event(_make_event("tool_end", {
                    "tool_call_id": tc_id,
                    "output": "",
                    "error": None,
                }))

            session.buffer_event(_make_event("lifecycle", {"event": "completed", "graph_name": "cv_agent"}))

        except Exception as e:
            session.buffer_event(_make_event("lifecycle", {
                "event": "failed",
                "error": str(e),
                "graph_name": "cv_agent",
            }))
        finally:
            session._running = False
            await db.close()

    session._task = asyncio.create_task(run())
    return run_id


async def stream_events(
    thread_id: str,
    channels: list[str],
    since: int = 0,
) -> AsyncGenerator[str, None]:
    session = session_manager.get(thread_id)
    q = session.subscribe()

    try:
        for event in session.get_events_since(since, channels):
            yield _encode_sse(event)

        while True:
            try:
                event = await asyncio.wait_for(q.get(), timeout=30)
                if event["method"] in channels or "*" in channels:
                    yield _encode_sse(event)
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
    finally:
        session.unsubscribe(q)


def _encode_sse(event: dict) -> str:
    event_id = event.get("event_id", "")
    id_line = f"id: {event_id}\n" if event_id else ""
    event_type = event.get("method", "message")
    data = json.dumps({k: v for k, v in event.items() if k not in ("seq",)})
    return f"{id_line}event: {event_type}\ndata: {data}\n\n"
