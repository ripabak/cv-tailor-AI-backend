from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..database import get_db
from ..models import Template
from ..schemas import TemplateResponse

router = APIRouter(prefix="/api/templates", tags=["templates"])


@router.get("", response_model=list[TemplateResponse])
async def list_templates(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Template).where(Template.is_published == True).order_by(Template.created_at.desc())
    )
    templates = result.scalars().all()
    return [TemplateResponse.model_validate(t) for t in templates]
