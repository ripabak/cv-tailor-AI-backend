import re
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from .base import BaseTool
from ...models import CVVersion, UserCV


def _extract_title(html: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    return m.group(1).strip() if m else "Untitled CV"


class GetCurrentHTMLTool(BaseTool):
    name = "get_current_html"
    description = "Read the current CV HTML content. No input needed."

    def __init__(self, db: AsyncSession, cv_id: int):
        super().__init__()
        self._db = db
        self._cv_id = cv_id

    async def execute(self, query: str) -> str:
        result = await self._db.execute(
            select(CVVersion)
            .where(CVVersion.user_cv_id == self._cv_id)
            .order_by(CVVersion.created_at.desc())
            .limit(1)
        )
        version = result.scalar_one_or_none()
        if not version:
            return "No CV HTML found."
        html = version.html_content
        lines = html.strip().split("\n")
        self._emit("tool_result", f"✅ CV loaded ({len(html)} chars, ~{len(lines)} lines)")
        return html


class EditCVTool(BaseTool):
    name = "edit_cv"
    description = "Save NEW HTML content directly. Input: the COMPLETE new HTML starting with <html>."

    def __init__(self, db: AsyncSession, cv_id: int):
        super().__init__()
        self._db = db
        self._cv_id = cv_id

    async def execute(self, query: str) -> str:
        html = query.strip()
        if not html.lower().startswith("<html"):
            return "Error: HTML must start with <html> tag"

        title = _extract_title(html)
        if title and title != "Untitled CV":
            cv_result = await self._db.execute(select(UserCV).where(UserCV.id == self._cv_id))
            cv = cv_result.scalar_one_or_none()
            if cv:
                cv.title = title

        version = CVVersion(user_cv_id=self._cv_id, html_content=html)
        self._db.add(version)
        await self._db.commit()

        self._emit("tool_result", f"✅ CV saved. Title: {title}")
        return f"CV updated. Title: {title}"
