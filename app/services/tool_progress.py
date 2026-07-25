import asyncio
import contextvars
from collections.abc import Callable

_progress_emitter: contextvars.ContextVar[Callable[[str], None] | None] = (
    contextvars.ContextVar("tool_progress_emitter", default=None)
)


def set_progress_emitter(emitter: Callable[[str], None]) -> contextvars.Token:
    return _progress_emitter.set(emitter)


def reset_progress_emitter(token: contextvars.Token):
    _progress_emitter.reset(token)


async def emit_progress(message: str):
    emitter = _progress_emitter.get()
    if emitter:
        emitter(message)
        await asyncio.sleep(0)
