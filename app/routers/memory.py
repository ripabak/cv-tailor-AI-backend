import datetime
import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from ..agent.memory_store import get_memory_store, user_namespace
from ..auth import get_current_user
from ..models import User
from ..schemas import (
    MemoryFactCreate,
    MemoryFactUpdate,
    MemoryFactResponse,
    MemoryListResponse,
)

router = APIRouter(prefix="/api/memory", tags=["memory"])


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _to_response(key: str, value: dict) -> MemoryFactResponse:
    return MemoryFactResponse(
        key=key,
        category=value.get("category", ""),
        content=value.get("content", ""),
        updated_at=value.get("updated_at", ""),
    )


@router.get("/categories", response_model=list[str])
async def list_categories(user: User = Depends(get_current_user)):
    """List distinct categories used by the user's memory facts."""
    store = get_memory_store()
    items = await store.asearch(user_namespace(user.id), limit=200)
    categories = {
        (item.value or {}).get("category", "").strip().lower()
        for item in items
        if (item.value or {}).get("category")
    }
    return sorted(categories)


@router.get("", response_model=MemoryListResponse)
async def list_memory(user: User = Depends(get_current_user)):
    store = get_memory_store()
    items = await store.asearch(user_namespace(user.id), limit=200)
    facts = [_to_response(item.key, item.value or {}) for item in items]
    return MemoryListResponse(facts=facts)


@router.post("", response_model=MemoryFactResponse, status_code=status.HTTP_201_CREATED)
async def create_memory(
    data: MemoryFactCreate,
    user: User = Depends(get_current_user),
):
    store = get_memory_store()
    namespace = user_namespace(user.id)

    key = uuid.uuid4().hex
    now = _now()
    value = {
        "category": data.category,
        "content": data.content,
        "created_at": now,
        "updated_at": now,
    }
    await store.aput(namespace, key, value)
    return _to_response(key, value)


@router.patch("/{key}", response_model=MemoryFactResponse)
async def update_memory(
    key: str,
    data: MemoryFactUpdate,
    user: User = Depends(get_current_user),
):
    store = get_memory_store()
    namespace = user_namespace(user.id)

    existing = await store.aget(namespace, key)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory fact not found")

    value = existing.value or {}
    value["content"] = data.content
    value["updated_at"] = _now()
    await store.aput(namespace, key, value)
    return _to_response(key, value)


@router.delete("/{key}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(
    key: str,
    user: User = Depends(get_current_user),
):
    store = get_memory_store()
    namespace = user_namespace(user.id)

    existing = await store.aget(namespace, key)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory fact not found")

    await store.adelete(namespace, key)
