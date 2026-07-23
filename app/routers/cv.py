import re
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ..database import get_db
from ..models import User, UserCV, CVVersion, Template
from ..schemas import (
    CVCreate, CVResponse, CVDetailResponse,
    CVVersionResponse,
)
from ..auth import get_current_user

router = APIRouter(prefix="/api/cv", tags=["cv"])


def extract_title(html: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()
    return "Untitled CV"


@router.get("", response_model=list[CVResponse])
async def list_cvs(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserCV).where(UserCV.user_id == user.id).order_by(UserCV.updated_at.desc())
    )
    cvs = result.scalars().all()
    return [CVResponse.model_validate(cv) for cv in cvs]


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
        .options(selectinload(UserCV.versions), selectinload(UserCV.template))
        .where(UserCV.id == cv_id, UserCV.user_id == user.id)
    )
    cv = result.scalar_one_or_none()
    if not cv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CV not found")

    latest_html = cv.versions[0].html_content if cv.versions else None
    return CVDetailResponse(
        id=cv.id,
        user_id=cv.user_id,
        template_id=cv.template_id,
        title=cv.title,
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

    new_version = CVVersion(user_cv_id=cv.id, html_content=source_version.html_content)
    db.add(new_version)
    await db.commit()
    await db.refresh(new_version)

    return CVVersionResponse.model_validate(new_version)
