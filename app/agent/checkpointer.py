from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from ..config import DATABASE_URL


_saver: AsyncPostgresSaver | None = None
_saver_cm = None


def _psycopg_url() -> str:
    url = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    if "?" not in url:
        url += "?sslmode=disable"
    return url


async def init_checkpointer() -> None:
    global _saver, _saver_cm
    if _saver is not None:
        return
    _saver_cm = AsyncPostgresSaver.from_conn_string(_psycopg_url())
    _saver = await _saver_cm.__aenter__()
    await _saver.setup()


async def close_checkpointer() -> None:
    global _saver, _saver_cm
    if _saver_cm is not None:
        await _saver_cm.__aexit__(None, None, None)
        _saver_cm = None
    _saver = None


def get_checkpointer() -> AsyncPostgresSaver:
    if _saver is None:
        raise RuntimeError("Checkpointer is not initialized. Call init_checkpointer() on startup.")
    return _saver
