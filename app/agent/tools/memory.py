import datetime
import uuid

from langgraph.store.postgres import AsyncPostgresStore
from langchain.tools import tool

from ...services.tool_progress import emit_progress
from ..memory_store import user_namespace


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def create_memory_tools(store: AsyncPostgresStore, user_id: int) -> list:
    namespace = user_namespace(user_id)

    @tool
    async def get_memory(category: str = "") -> str:
        """Read the user's saved long-term memory facts about themselves.

        Call this to personalize the CV with known facts about the user
        (contacts, experience, education, skills, target roles, preferences)
        before editing.

        Args:
            category: Optional filter to read facts of ONE category only (e.g. "pengalaman").
                      Leave empty to read ALL facts."""
        await emit_progress("Reading long-term memory...")

        items = await store.asearch(namespace, limit=200)
        lines = []
        for item in items:
            value = item.value or {}
            cat = value.get("category", "?")
            content = value.get("content", "")
            if category and cat.lower() != category.lower():
                continue
            lines.append(f"- ({cat}) {content}")

        if not lines:
            if category:
                await emit_progress(f"No memory facts in category '{category}'.")
                return f"No long-term memory facts saved in category '{category}'."
            await emit_progress("No memory facts found yet.")
            return "No long-term memory facts saved. The user has not shared personal facts yet."

        await emit_progress(f"Loaded {len(lines)} memory fact(s).")
        return "=== LONG-TERM MEMORY ===\n" + "\n".join(lines)

    @tool
    async def save_fact(category: str, content: str, key: str = "") -> str:
        """Save or update a long-term memory fact about the user.

        Use when the user shares personal information that should be remembered
        for future CV personalization (e.g. "I worked at Gojek for 3 years",
        "my email is x@y.com", target roles, preferences).

        Args:
            category: Free-form category. Examples: kontak, pengalaman, pendidikan,
                      skill, bahasa, target, preferensi, sertifikasi, proyek,
                      penghargaan, minat. Use a new category if none fits.
            content: The fact itself, written as a concise statement. For
                     pengalaman/proyek facts include FULL details: position,
                     company, duration, and what was done (responsibilities,
                     tech, scale, results) — e.g. "Backend Engineer di Gojek
                     (2021-2024). Membangun API pembayaran (Python, PostgreSQL),
                     2M request/hari, mentoring 2 junior."
            key: The fact key to OVERWRITE (from get_memory output). Leave empty to create a new fact."""
        now = _now()

        if key:
            existing = await store.aget(namespace, key)
            if existing is None:
                return f"ERROR: key '{key}' not found. Use get_memory to see existing fact keys."
            value = existing.value or {}
            value.update({
                "category": category,
                "content": content,
                "updated_at": now,
            })
            await store.aput(namespace, key, value)
            await emit_progress(f"Updated memory fact ({category}).")
            return f"Updated fact '{key}' ({category})."

        new_key = uuid.uuid4().hex
        await store.aput(namespace, new_key, {
            "category": category,
            "content": content,
            "created_at": now,
            "updated_at": now,
        })
        await emit_progress(f"Saved memory fact ({category}).")
        return f"Saved new fact '{new_key}' ({category})."

    @tool
    async def delete_fact(key: str) -> str:
        """Delete a long-term memory fact about the user.

        Use when the user retracts or corrects previously saved information.

        Args:
            key: The fact key to delete (from get_memory output)."""
        existing = await store.aget(namespace, key)
        if existing is None:
            return f"ERROR: key '{key}' not found. Use get_memory to see existing fact keys."
        await store.adelete(namespace, key)
        await emit_progress("Deleted memory fact.")
        return f"Deleted fact '{key}'."

    return [get_memory, save_fact, delete_fact]
