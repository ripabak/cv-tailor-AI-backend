import re
from langchain.tools import tool
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ...models import CVVersion, UserCV
from ...services.tool_progress import emit_progress


def _flexible_find(html: str, needle: str) -> tuple[int, int] | None:
    """Find needle in html with flexible whitespace handling. Returns (start, end) or None."""
    parts: list[str] = []
    i = 0
    while i < len(needle):
        if needle[i] in ' \t\n\r':
            while i < len(needle) and needle[i] in ' \t\n\r':
                i += 1
            parts.append(r'\s+')
        else:
            c = needle[i]
            parts.append(re.escape(c))
            i += 1
    pattern = ''.join(parts)
    m = re.search(pattern, html)
    return (m.start(), m.end()) if m else None


def _try_replace_flexible(html: str, old_content: str, new_content: str) -> str | None:
    """Fallback: replace using flexible whitespace matching. Returns new_html or None."""
    r = _flexible_find(html, old_content)
    if r is not None:
        return html[:r[0]] + new_content + html[r[1]:]
    return None


def create_tools(db: AsyncSession, cv_id: int) -> list:
    @tool
    async def get_current_html() -> str:
        """Read the current CV HTML content and title. Call this first before making any edits."""
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

        await emit_progress(f"Loaded CV HTML ({len(version.html_content)} chars), title: {cv.title}")
        return f"=== CV TITLE: {cv.title} ===\n\n{version.html_content}"

    @tool
    async def cv_replace(old_content: str, new_content: str) -> str:
        """Replace a block in the CV HTML using direct search-and-replace. No LLM call needed.

        Use this for targeted, precise edits when you know exactly what block to replace.
        It does NOT call the LLM to regenerate the entire HTML.

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

        new_html: str | None = None
        count = current_html.count(old_content)

        if count == 0:
            new_html = _try_replace_flexible(current_html, old_content, new_content)
            if new_html is not None:
                await emit_progress("Block matched via flexible whitespace normalization")
                count = 1
            else:
                return f"ERROR: old_content not found in the HTML. It may have changed since you last read it. Call get_current_html again, then retry with the exact block."

        if count > 1:
            return f"ERROR: old_content matched {count} times. Provide a larger, more specific block (include surrounding context) to uniquely identify the target."

        await emit_progress(f"Found block ({len(old_content)} chars), replacing with new content ({len(new_content)} chars)...")

        if new_html is None:
            new_html = current_html.replace(old_content, new_content, 1)

        if cv:
            new_version = CVVersion(user_cv_id=cv_id, html_content=new_html, parent_version_id=version.id)
            db.add(new_version)
            await db.flush()
            cv.current_version_id = new_version.id

        await db.commit()

        await emit_progress(f"Replace completed.")
        return f"Block replaced successfully ({count} occurrence)."

    @tool
    async def cv_replace_all(old_content: str, new_content: str) -> str:
        """Replace ALL occurrences of a block in the CV HTML using direct search-and-replace.

        Use this when you want to replace a pattern that appears multiple times.
        It does NOT call the LLM to regenerate the entire HTML.

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

        new_html: str | None = None
        count = current_html.count(old_content)

        if count == 0:
            flexible = _try_replace_flexible(current_html, old_content, new_content)
            if flexible is not None:
                await emit_progress("Block matched via flexible whitespace normalization")
                new_html = flexible
                count = 1
            else:
                return f"ERROR: old_content not found in the HTML. It may have changed since you last read it. Call get_current_html again, then retry with the exact block."

        await emit_progress(f"Found {count} occurrences, replacing all...")

        if new_html is None:
            new_html = current_html.replace(old_content, new_content)

        if cv:
            new_version = CVVersion(user_cv_id=cv_id, html_content=new_html, parent_version_id=version.id)
            db.add(new_version)
            await db.flush()
            cv.current_version_id = new_version.id

        await db.commit()

        await emit_progress(f"Replace completed.")
        return f"Replaced {count} occurrence(s) successfully."

    @tool
    async def read_lines(start_line: int, end_line: int) -> str:
        """Read a specific range of lines from the CV HTML. Line numbers start at 1.

        Use this to inspect a specific section without loading the entire HTML.
        The output includes line numbers for easy reference when using edit_lines.
        Both start_line and end_line are INCLUSIVE.

        Args:
            start_line: First line to read (1-indexed, inclusive).
            end_line: Last line to read (1-indexed, inclusive)."""

        cv_result = await db.execute(select(UserCV).where(UserCV.id == cv_id))
        cv = cv_result.scalar_one_or_none()
        if not cv or not cv.current_version_id:
            return "No CV HTML found."

        result = await db.execute(
            select(CVVersion).where(CVVersion.id == cv.current_version_id)
        )
        version = result.scalar_one_or_none()
        if not version:
            return "No CV HTML found."

        lines = version.html_content.split('\n')
        total = len(lines)

        start = max(0, start_line - 1)
        end = min(total, end_line)

        if start >= total:
            return f"start_line {start_line} is beyond the total line count ({total})."

        output_lines: list[str] = []
        for i in range(start, end):
            output_lines.append(f"{i + 1:4d}: {lines[i]}")

        await emit_progress(f"Read lines {start + 1}-{end} of {total}")
        return '\n'.join(output_lines)

    @tool
    async def edit_lines(start_line: int, end_line: int, new_content: str) -> str:
        """Replace a range of lines in the CV HTML. Line numbers start at 1.

        This is the PREFERRED way to make edits — more reliable than cv_replace because
        it uses exact line positions instead of string matching.
        Both start_line and end_line are INCLUSIVE.

        MUST call read_lines FIRST to verify the exact lines you want to edit.
        If the read_lines output does not match the section you expect, call read_lines
        again with different numbers until you find the correct section.

        Args:
            start_line: First line to replace (1-indexed, inclusive).
            end_line: Last line to replace (1-indexed, inclusive).
            new_content: The new content to insert in place of the removed lines.
                         Can be multiple lines (separated by newlines)."""

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

        lines = version.html_content.split('\n')
        total = len(lines)

        start = start_line - 1
        end = end_line

        if start < 0:
            return f"start_line must be >= 1, got {start_line}."
        if end > total:
            end = total
        if start >= total:
            return f"start_line {start_line} is beyond the total line count ({total})."
        if start > end:
            return f"start_line ({start_line}) must be <= end_line ({end_line})."

        replaced_count = end - start
        new_lines = lines[:start] + [new_content] + lines[end:]
        new_html = '\n'.join(new_lines)

        await emit_progress(f"Replaced lines {start_line} to {end_line} ({replaced_count} lines) with {len(new_content)} chars")

        if cv:
            new_version = CVVersion(user_cv_id=cv_id, html_content=new_html, parent_version_id=version.id)
            db.add(new_version)
            await db.flush()
            cv.current_version_id = new_version.id

        await db.commit()

        await emit_progress(f"Edit completed.")
        return f"Lines {start_line} to {end_line} replaced successfully."

    @tool
    async def set_cv_title(title: str) -> str:
        """Set the CV title. The title should be concise (max ~60 chars), describing the job target.
        Example: "Budi Santoso - Software Engineer CV"

        Args:
            title: The new title for this CV."""
        cv_result = await db.execute(select(UserCV).where(UserCV.id == cv_id))
        cv = cv_result.scalar_one_or_none()
        if not cv:
            return "CV not found."
        cv.title = title[:200]
        await db.commit()
        await emit_progress(f"CV title set to: {title[:200]}")
        return f"Title set to: {title[:200]}"

    return [get_current_html, read_lines, edit_lines, cv_replace, cv_replace_all, set_cv_title]

