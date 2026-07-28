import json
import asyncio
import uuid
from collections import defaultdict
from typing import AsyncGenerator

from ..agent.agent import build_agent
from ..database import async_session
from .tool_progress import set_progress_emitter, reset_progress_emitter


class AgentSession:
    def __init__(self):
        self.run_id: str | None = None
        self.events: list[dict] = []
        self.subscribers: list[asyncio.Queue] = []
        self._running = False
        self._task: asyncio.Task | None = None
        self._seq = 0
        self.total_usage: dict = {}

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


def stop_agent_run(thread_id: str):
    session = session_manager.get(thread_id)
    if session._task and not session._task.done():
        session._task.cancel()


def _make_event(method: str, data) -> dict:
    return {
        "method": method,
        "params": {
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

            session.buffer_event(_make_event("lifecycle", {"event": "running"}))

            current_msg_id: str | None = None
            _last_tool_call_id: str = ""

            def _on_tool_progress(message: str):
                session.buffer_event(_make_event("tool_progress", {
                    "tool_call_id": _last_tool_call_id,
                    "message": message,
                }))

            token = set_progress_emitter(_on_tool_progress)

            async for event in stream:
                method = event.get("method", "")
                params = event.get("params", {}) or {}
                raw_data = params.get("data", {})

                if method == "messages":
                    msg_event = raw_data[0] if isinstance(raw_data, tuple) else raw_data
                    if isinstance(msg_event, str):
                        continue
                    ev_type = msg_event.get("event", "")

                    if ev_type == "message-start":
                        current_msg_id = str(uuid.uuid4())
                        session.buffer_event(_make_event("message_start", {
                            "id": current_msg_id, "role": "assistant",
                        }))

                    elif ev_type == "content-block-delta":
                        delta = msg_event.get("delta", {})
                        if not current_msg_id:
                            continue
                        if delta.get("type") == "reasoning-delta" and delta.get("reasoning"):
                            session.buffer_event(_make_event("text_delta", {
                                "id": current_msg_id, "delta": delta["reasoning"], "kind": "reasoning",
                            }))
                        elif delta.get("type") == "text-delta" and delta.get("text"):
                            session.buffer_event(_make_event("text_delta", {
                                "id": current_msg_id, "delta": delta["text"], "kind": "text",
                            }))

                    elif ev_type == "message-finish":
                        if current_msg_id:
                            usage = msg_event.get("usage") or {}
                            metadata = msg_event.get("metadata") or {}
                            for k in ("input_tokens", "output_tokens", "total_tokens"):
                                session.total_usage[k] = session.total_usage.get(k, 0) + usage.get(k, 0)
                            session.total_usage["calls"] = session.total_usage.get("calls", 0) + 1
                            session.buffer_event(_make_event("message_end", {
                                "id": current_msg_id,
                                "usage": {
                                    "input_tokens": usage.get("input_tokens", 0),
                                    "output_tokens": usage.get("output_tokens", 0),
                                    "total_tokens": usage.get("total_tokens", 0),
                                    "cost": metadata.get("cost"),
                                },
                                "total_usage": session.total_usage.copy(),
                                "model": metadata.get("model_name"),
                            }))

                elif method == "tools":
                    ev_type = raw_data.get("event", "")

                    if ev_type == "tool-started":
                        _last_tool_call_id = raw_data.get("tool_call_id", "")
                        session.buffer_event(_make_event("tool_start", {
                            "tool_call_id": _last_tool_call_id,
                            "name": raw_data.get("tool_name", ""),
                            "args": raw_data.get("input", {}),
                        }))

                    elif ev_type == "tool-finished":
                        tc_id = raw_data.get("tool_call_id", "")
                        output = raw_data.get("output", "")
                        session.buffer_event(_make_event("tool_end", {
                            "tool_call_id": tc_id,
                            "output": str(output) if output else "",
                            "error": None,
                        }))

            session.buffer_event(_make_event("lifecycle", {"event": "completed"}))

        except asyncio.CancelledError:
            session.buffer_event(_make_event("lifecycle", {
                "event": "cancelled",
            }))
        except Exception as e:
            session.buffer_event(_make_event("lifecycle", {
                "event": "failed",
                "error": str(e),
            }))
        finally:
            reset_progress_emitter(token)
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
