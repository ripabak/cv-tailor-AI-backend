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
    async def list_categories() -> str:
        """List all distinct categories used across the user's long-term memory facts.

        Use to discover what categories are available before reading or deleting facts
        by category."""
        items = await store.asearch(namespace, limit=200)
        categories = {
            value.get("category", "").strip().lower()
            for item in items
            if (value := item.value) and value.get("category")
        }
        if not categories:
            return "No memory facts found. The user has not shared any facts yet."
        return "=== AVAILABLE CATEGORIES ===\n" + "\n".join(
            f"- {c}" for c in sorted(categories)
        )

    @tool
    async def get_memory(category: str = "", limit: int = 50, offset: int = 0) -> str:
        """Read the user's saved long-term memory facts about themselves.

        Call this to personalize the CV with known facts about the user
        (contacts, experience, education, skills, target roles, preferences)
        before editing. The output includes per-fact keys needed for delete_fact
        and save_fact(key=...) operations.

        Args:
            category: Optional filter to read facts of ONE category only (e.g. "pengalaman").
                      Leave empty to read ALL facts.
            limit: Max facts to return (default 50). Increase for more, decrease for fewer.
            offset: Number of facts to skip (for pagination). Use with limit to read
                    incrementally: first call offset=0, then offset=50, etc."""
        await emit_progress("Reading long-term memory...")

        items = await store.asearch(namespace, limit=limit, offset=offset)
        lines = []
        for item in items:
            value = item.value or {}
            cat = value.get("category", "?")
            content = value.get("content", "")
            if category and cat.lower() != category.lower():
                continue
            lines.append(f"- [{item.key}] ({cat}) {content}")

        if not lines:
            if category:
                await emit_progress(f"No memory facts in category '{category}'.")
                return f"No long-term memory facts saved in category '{category}'."
            await emit_progress("No memory facts found yet.")
            return "No long-term memory facts saved. The user has not shared personal facts yet."

        total = len(lines)
        if total >= limit:
            suffix = f"\n(Showing {total} of up to {limit} results. Use offset={offset + limit} for next page.)"
        else:
            suffix = ""
        await emit_progress(f"Loaded {total} memory fact(s).")
        return f"=== LONG-TERM MEMORY ===\n" + "\n".join(lines) + suffix

    @tool
    async def save_fact(category: str, content: str, key: str = "") -> str:
        """Save or update a long-term memory fact about the user.

        Use when the user shares personal information that should be remembered
        for future CV personalization (e.g. "I worked at Gojek for 3 years",
        "my email is x@y.com", target roles, preferences).

        Args:
            category: Free-form category. Examples: contact, experience, education,
                      skill, language, target, preference, certification, project,
                      award, interest. Use a new category if none fits.
            content: The fact itself, written as a concise statement. For
                     experience/project facts include FULL details: position,
                     company, duration, and what was done (responsibilities,
                     tech, scale, results) — e.g. "Backend Engineer at Gojek
                     (2021-2024). Built payment APIs (Python, PostgreSQL),
                     handled 2M requests/day, mentored 2 juniors."
            key: The fact key to OVERWRITE (from get_memory output, shown in brackets [key]).
                 Leave empty to create a new fact."""
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
    async def delete_fact(key: str = "", category: str = "") -> str:
        """Delete one or more long-term memory facts about the user.

        Use when the user retracts previously saved information or wants to
        clean up certain categories. Provide exactly one filter parameter
        (key or category), not both.

        Args:
            key: The fact key to delete ONE fact (from get_memory output, shown in brackets [key]).
            category: Delete ALL facts matching this category (case-insensitive).
                      Requires explicit confirmation from user before executing."""
        if key and category:
            return "ERROR: provide only one of 'key' or 'category', not both."

        if not key and not category:
            return "ERROR: provide either 'key' or 'category' to identify what to delete."

        if key:
            existing = await store.aget(namespace, key)
            if existing is None:
                return f"ERROR: key '{key}' not found. Use get_memory to see existing fact keys."
            await store.adelete(namespace, key)
            await emit_progress("Deleted memory fact.")
            return f"Deleted fact '{key}'."

        items = await store.asearch(namespace, limit=200)
        matched = [
            item for item in items
            if (item.value or {}).get("category", "").lower() == category.lower()
        ]
        if not matched:
            return f"No facts found in category '{category}'. Use list_categories to see available categories."

        for item in matched:
            await store.adelete(namespace, item.key)
        await emit_progress(f"Deleted {len(matched)} memory facts ({category}).")
        return f"Deleted {len(matched)} fact(s) in category '{category}'."

    return [list_categories, get_memory, save_fact, delete_fact]
