import math
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select

from ..database import get_db
from ..models import Template
from ..schemas import PaginatedTemplateResponse, TemplateResponse

router = APIRouter(prefix="/api/templates", tags=["templates"])


@router.get("", response_model=PaginatedTemplateResponse)
async def list_templates(
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(9, ge=1, le=50),
):
    count_result = await db.execute(
        select(func.count()).select_from(Template).where(Template.is_published == True)
    )
    total = count_result.scalar()

    result = await db.execute(
        select(Template)
        .where(Template.is_published == True)
        .order_by(Template.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    templates = result.scalars().all()

    return PaginatedTemplateResponse(
        items=[TemplateResponse.model_validate(t) for t in templates],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=math.ceil(total / page_size) if total > 0 else 1,
    )
