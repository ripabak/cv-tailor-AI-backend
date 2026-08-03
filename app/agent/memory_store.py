from langgraph.store.postgres import AsyncPostgresStore

from ..config import DATABASE_URL


_store: AsyncPostgresStore | None = None
_store_cm = None


def _psycopg_url() -> str:
    url = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    if "?" not in url:
        url += "?sslmode=disable"
    return url


def user_namespace(user_id: int) -> tuple[str, ...]:
    return ("user", str(user_id))


async def init_memory_store() -> None:
    global _store, _store_cm
    if _store is not None:
        return
    _store_cm = AsyncPostgresStore.from_conn_string(_psycopg_url())
    _store = await _store_cm.__aenter__()
    await _store.setup()


async def close_memory_store() -> None:
    global _store, _store_cm
    if _store_cm is not None:
        await _store_cm.__aexit__(None, None, None)
        _store_cm = None
    _store = None


def get_memory_store() -> AsyncPostgresStore:
    if _store is None:
        raise RuntimeError("Memory store is not initialized. Call init_memory_store() on startup.")
    return _store
