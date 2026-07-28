import re
import httpx
from langchain.tools import tool
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ...models import CVVersion, UserCV
from ...config import OPENROUTER_API_KEY, OPENROUTER_BASE_URL, OPENROUTER_MODEL
from ...services.tool_progress import emit_progress


EDIT_SYSTEM_PROMPT = """You are an HTML editor. You receive the current CV HTML and a change description.
Output ONLY the complete modified HTML starting with <html>. Do NOT output explanations.
Preserve all Tailwind CSS classes, layout, and structure. Only change what is requested.
Remove any .print-hide elements and @media print .print-hide CSS rules found in the HTML."""


def _extract_title(html: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    return m.group(1).strip() if m else "Untitled CV"


def _strip_fences(html: str) -> str:
    html = html.strip()
    if html.startswith("```html"):
        html = html[7:]
    elif html.startswith("```"):
        html = html[3:]
    if html.endswith("```"):
        html = html[:-3]
    return html.strip()


async def _call_llm(messages: list[dict]) -> str:
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{OPENROUTER_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": OPENROUTER_MODEL,
                "messages": messages,
                "temperature": 0.3,
                "max_tokens": 8192,
            },
        )
        data = resp.json()
        if "error" in data:
            raise RuntimeError(data["error"].get("message", str(data["error"])))
        return data["choices"][0]["message"]["content"]


def create_tools(db: AsyncSession, cv_id: int) -> list:
    @tool
    async def get_current_html() -> str:
        """Read the current CV HTML content. Call this first before making any edits."""
        await emit_progress("Reading current CV HTML from database...")

        cv_result = await db.execute(select(UserCV).where(UserCV.id == cv_id))
        cv = cv_result.scalar_one_or_none()
        if not cv or not cv.current_version_id:
            await emit_progress("No existing CV HTML found.")
            return "No CV HTML found."

        result = await db.execute(
            select(CVVersion).where(CVVersion.id == cv.current_version_id)
        )
        version = result.scalar_one_or_none()
        if not version:
            await emit_progress("No existing CV HTML found.")
            return "No CV HTML found."

        await emit_progress(f"Loaded CV HTML ({len(version.html_content)} chars)")
        return version.html_content

    @tool
    async def cv_replace(old_content: str, new_content: str) -> str:
        """Replace a block in the CV HTML using direct search-and-replace. No LLM call needed.

        Use this for targeted, precise edits when you know exactly what block to replace.
        MUCH faster than edit_cv because it does NOT call the LLM to regenerate the entire HTML.

        Args:
            old_content: The exact HTML block to find. Copy it verbatim from get_current_html.
            new_content: The replacement HTML block.

        Returns:
            Confirmation message or error if the block was not found or matched multiple times."""
        await emit_progress("Reading current CV HTML...")
        cv_result = await db.execute(select(UserCV).where(UserCV.id == cv_id))
        cv = cv_result.scalar_one_or_none()
        if not cv or not cv.current_version_id:
            return "No CV HTML found to edit."

        result = await db.execute(
            select(CVVersion).where(CVVersion.id == cv.current_version_id)
        )
        version = result.scalar_one_or_none()
        if not version:
            return "No CV HTML found to edit."

        current_html = version.html_content

        count = current_html.count(old_content)
        if count == 0:
            return f"ERROR: old_content not found in the HTML. It may have changed since you last read it. Call get_current_html again, then retry with the exact block."

        if count > 1:
            return f"ERROR: old_content matched {count} times. Provide a larger, more specific block (include surrounding context) to uniquely identify the target."

        await emit_progress(f"Found block ({len(old_content)} chars), replacing with new content ({len(new_content)} chars)...")

        new_html = current_html.replace(old_content, new_content, 1)

        title = _extract_title(new_html)
        if cv and title and title != "Untitled CV":
            cv.title = title
        if cv:
            new_version = CVVersion(user_cv_id=cv_id, html_content=new_html, parent_version_id=version.id)
            db.add(new_version)
            await db.flush()
            cv.current_version_id = new_version.id

        await db.commit()

        await emit_progress(f"Replace completed. Title: {title}")
        return f"Block replaced successfully ({count} occurrence). Title: {title}"

    @tool
    async def cv_replace_all(old_content: str, new_content: str) -> str:
        """Replace ALL occurrences of a block in the CV HTML using direct search-and-replace.

        Use this when you want to replace a pattern that appears multiple times.
        Faster than edit_cv because it does NOT call the LLM.

        Args:
            old_content: The HTML block to find and replace everywhere.
            new_content: The replacement HTML block.

        Returns:
            Confirmation with count of replacements or error if nothing was found."""
        await emit_progress("Reading current CV HTML...")
        cv_result = await db.execute(select(UserCV).where(UserCV.id == cv_id))
        cv = cv_result.scalar_one_or_none()
        if not cv or not cv.current_version_id:
            return "No CV HTML found to edit."

        result = await db.execute(
            select(CVVersion).where(CVVersion.id == cv.current_version_id)
        )
        version = result.scalar_one_or_none()
        if not version:
            return "No CV HTML found to edit."

        current_html = version.html_content

        count = current_html.count(old_content)
        if count == 0:
            return f"ERROR: old_content not found in the HTML. It may have changed since you last read it. Call get_current_html again, then retry with the exact block."

        await emit_progress(f"Found {count} occurrences, replacing all...")

        new_html = current_html.replace(old_content, new_content)

        title = _extract_title(new_html)
        if cv and title and title != "Untitled CV":
            cv.title = title
        if cv:
            new_version = CVVersion(user_cv_id=cv_id, html_content=new_html, parent_version_id=version.id)
            db.add(new_version)
            await db.flush()
            cv.current_version_id = new_version.id

        await db.commit()

        await emit_progress(f"Replace completed. Title: {title}")
        return f"Replaced {count} occurrence(s) successfully. Title: {title}"

    @tool
    async def edit_cv(prompt: str) -> str:
        """Apply changes to the CV via LLM. Input is a detailed prompt describing the changes.
        The tool will read current HTML, call LLM to generate a new version, and save it.

        PREFER cv_replace or cv_replace_all for targeted edits — they are much faster.
        Use edit_cv only for complex structural changes that cannot be expressed as block replacement."""

        await emit_progress("Reading current CV HTML...")
        cv_result = await db.execute(select(UserCV).where(UserCV.id == cv_id))
        cv = cv_result.scalar_one_or_none()
        if not cv or not cv.current_version_id:
            return "No CV HTML found to edit."

        result = await db.execute(
            select(CVVersion).where(CVVersion.id == cv.current_version_id)
        )
        version = result.scalar_one_or_none()
        if not version:
            return "No CV HTML found to edit."

        current_html = version.html_content
        await emit_progress(f"Read HTML ({len(current_html)} chars)")

        await emit_progress("Generating modified HTML via LLM...")
        new_html = await _call_llm([
            {"role": "system", "content": EDIT_SYSTEM_PROMPT},
            {"role": "user", "content": f"Current HTML:\n\n{current_html}\n\nChange request: {prompt}\n\nOutput ONLY the complete modified HTML:"},
        ])
        new_html = _strip_fences(new_html)

        if not new_html.lower().startswith("<html"):
            await emit_progress("LLM did not return valid HTML, retrying...")
            new_html = await _call_llm([
                {"role": "system", "content": EDIT_SYSTEM_PROMPT},
                {"role": "user", "content": f"Current HTML:\n\n{current_html}\n\nChange request: {prompt}"},
                {"role": "assistant", "content": new_html},
                {"role": "user", "content": "The output must start with <html> and contain NO markdown fences. Output ONLY the complete HTML:"},
            ])
            new_html = _strip_fences(new_html)

        await emit_progress(f"Generated HTML ({len(new_html)} chars)")

        await emit_progress("Validating and extracting title...")
        title = _extract_title(new_html)
        if cv and title and title != "Untitled CV":
            cv.title = title
        if cv:
            new_version = CVVersion(user_cv_id=cv_id, html_content=new_html, parent_version_id=version.id)
            db.add(new_version)
            await db.flush()
            cv.current_version_id = new_version.id

        await db.commit()

        await emit_progress(f"CV saved successfully. Title: {title}")
        return f"CV updated successfully. Title: {title}"

    return [get_current_html, cv_replace, cv_replace_all, edit_cv]

