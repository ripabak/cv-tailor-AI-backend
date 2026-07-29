from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from ..database import get_db
from ..models import UserCV

router = APIRouter(prefix="/view", tags=["public-view"])


@router.get("/{slug}", response_class=HTMLResponse)
async def view_cv_page(
    slug: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserCV)
        .options(joinedload(UserCV.current_version), joinedload(UserCV.template))
        .where(UserCV.public_slug == slug, UserCV.is_published == True)
    )
    cv = result.scalar_one_or_none()
    if not cv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CV not found")

    latest_html = cv.current_version.html_content if cv.current_version else (
        cv.template.html_code if cv.template else ""
    )

    return HTMLResponse(content=latest_html)
