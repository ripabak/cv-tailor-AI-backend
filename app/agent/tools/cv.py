import re
from typing import Callable, Awaitable
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ...models import CVVersion, UserCV


def _extract_title(html: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    return m.group(1).strip() if m else "Untitled CV"


def create_tools(db: AsyncSession, cv_id: int) -> list[Callable]:
    async def get_current_html() -> str:
        """Read the current CV HTML content. Call this first before making any edits."""
        result = await db.execute(
            select(CVVersion)
            .where(CVVersion.user_cv_id == cv_id)
            .order_by(CVVersion.created_at.desc())
            .limit(1)
        )
        version = result.scalar_one_or_none()
        if not version:
            return "No CV HTML found."
        return version.html_content

    async def edit_cv(html: str) -> str:
        """Save the complete new CV HTML. Input must be the FULL HTML starting with <html>. Do NOT send fragments or partial HTML."""
        html = html.strip()
        if not html.lower().startswith("<html"):
            return "Error: HTML must start with <html> tag. Please provide the COMPLETE HTML document."

        title = _extract_title(html)
        if title and title != "Untitled CV":
            cv_result = await db.execute(select(UserCV).where(UserCV.id == cv_id))
            cv = cv_result.scalar_one_or_none()
            if cv:
                cv.title = title

        version = CVVersion(user_cv_id=cv_id, html_content=html)
        db.add(version)
        await db.commit()

        return f"CV updated successfully. Title: {title}"

    return [get_current_html, edit_cv]
