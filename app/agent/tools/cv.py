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
Preserve all Tailwind CSS classes, layout, and structure. Only change what is requested."""


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

        result = await db.execute(
            select(CVVersion)
            .where(CVVersion.user_cv_id == cv_id)
            .order_by(CVVersion.created_at.desc())
            .limit(1)
        )
        version = result.scalar_one_or_none()
        if not version:
            await emit_progress("No existing CV HTML found.")
            return "No CV HTML found."

        await emit_progress(f"Loaded CV HTML ({len(version.html_content)} chars)")
        return version.html_content

    @tool
    async def edit_cv(prompt: str) -> str:
        """Apply changes to the CV. Input is a detailed prompt describing EXACTLY what to change in the HTML.
        The tool will read current HTML, generate a new version, and save it."""

        await emit_progress("Reading current CV HTML...")
        result = await db.execute(
            select(CVVersion)
            .where(CVVersion.user_cv_id == cv_id)
            .order_by(CVVersion.created_at.desc())
            .limit(1)
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
        if title and title != "Untitled CV":
            cv_result = await db.execute(select(UserCV).where(UserCV.id == cv_id))
            cv = cv_result.scalar_one_or_none()
            if cv:
                cv.title = title

        await emit_progress("Saving new CV version to database...")
        new_version = CVVersion(user_cv_id=cv_id, html_content=new_html)
        db.add(new_version)
        await db.commit()

        await emit_progress(f"CV saved successfully. Title: {title}")
        return f"CV updated successfully. Title: {title}"

    return [get_current_html, edit_cv]

