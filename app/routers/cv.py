import math
import re
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from ..database import get_db
from ..models import User, UserCV, CVVersion, Template
from ..schemas import (
    CVCreate, CVResponse, CVDetailResponse, PaginatedCVResponse,
    CVVersionResponse,
)
from ..auth import get_current_user

router = APIRouter(prefix="/api/cv", tags=["cv"])


def extract_title(html: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()
    return "Untitled CV"


@router.get("", response_model=PaginatedCVResponse)
async def list_cvs(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(9, ge=1, le=50),
):
    count_result = await db.execute(
        select(func.count()).select_from(UserCV).where(UserCV.user_id == user.id)
    )
    total = count_result.scalar()

    result = await db.execute(
        select(UserCV)
        .options(selectinload(UserCV.current_version), selectinload(UserCV.template))
        .where(UserCV.user_id == user.id)
        .order_by(UserCV.updated_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    cvs = result.scalars().all()

    items = []
    for cv in cvs:
        if cv.current_version:
            latest_html = cv.current_version.html_content
        elif cv.template:
            latest_html = cv.template.html_code
        else:
            latest_html = None
        items.append(CVResponse(
            id=cv.id,
            user_id=cv.user_id,
            template_id=cv.template_id,
            title=cv.title,
            current_version_id=cv.current_version_id,
            latest_html=latest_html,
            created_at=cv.created_at,
            updated_at=cv.updated_at,
        ))

    return PaginatedCVResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=math.ceil(total / page_size) if total > 0 else 1,
    )


@router.post("", response_model=CVDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_cv(
    data: CVCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    template_result = await db.execute(
        select(Template).where(Template.id == data.template_id, Template.is_published == True)
    )
    template = template_result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")

    title = extract_title(template.html_code)

    cv = UserCV(
        user_id=user.id,
        template_id=template.id,
        title=title,
    )
    db.add(cv)
    await db.flush()

    version = CVVersion(user_cv_id=cv.id, html_content=template.html_code)
    db.add(version)
    await db.flush()

    cv.current_version_id = version.id
    await db.commit()
    await db.refresh(cv)

    return CVDetailResponse(
        id=cv.id,
        user_id=cv.user_id,
        template_id=cv.template_id,
        title=cv.title,
        created_at=cv.created_at,
        updated_at=cv.updated_at,
        latest_html=template.html_code,
        template_title=template.title,
    )


@router.get("/{cv_id}", response_model=CVDetailResponse)
async def get_cv(
    cv_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserCV)
        .options(selectinload(UserCV.versions), selectinload(UserCV.template), selectinload(UserCV.current_version))
        .where(UserCV.id == cv_id, UserCV.user_id == user.id)
    )
    cv = result.scalar_one_or_none()
    if not cv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CV not found")

    latest_html = cv.current_version.html_content if cv.current_version else None
    return CVDetailResponse(
        id=cv.id,
        user_id=cv.user_id,
        template_id=cv.template_id,
        title=cv.title,
        current_version_id=cv.current_version_id,
        created_at=cv.created_at,
        updated_at=cv.updated_at,
        latest_html=latest_html,
        template_title=cv.template.title if cv.template else None,
    )


@router.delete("/{cv_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_cv(
    cv_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserCV).where(UserCV.id == cv_id, UserCV.user_id == user.id)
    )
    cv = result.scalar_one_or_none()
    if not cv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CV not found")

    await db.delete(cv)
    await db.commit()


@router.get("/{cv_id}/versions", response_model=list[CVVersionResponse])
async def list_versions(
    cv_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserCV).where(UserCV.id == cv_id, UserCV.user_id == user.id)
    )
    cv = result.scalar_one_or_none()
    if not cv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CV not found")

    versions_result = await db.execute(
        select(CVVersion)
        .where(CVVersion.user_cv_id == cv_id)
        .order_by(CVVersion.created_at.desc())
    )
    versions = versions_result.scalars().all()
    return [CVVersionResponse.model_validate(v) for v in versions]


@router.post("/{cv_id}/versions/{version_id}/revert", response_model=CVVersionResponse)
async def revert_version(
    cv_id: int,
    version_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cv_result = await db.execute(
        select(UserCV).where(UserCV.id == cv_id, UserCV.user_id == user.id)
    )
    cv = cv_result.scalar_one_or_none()
    if not cv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CV not found")

    version_result = await db.execute(
        select(CVVersion).where(
            CVVersion.id == version_id, CVVersion.user_cv_id == cv_id
        )
    )
    source_version = version_result.scalar_one_or_none()
    if not source_version:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")

    cv.current_version_id = source_version.id
    title = extract_title(source_version.html_content)
    if title and title != "Untitled CV":
        cv.title = title
    await db.commit()
    await db.refresh(cv)

    return CVVersionResponse.model_validate(source_version)
