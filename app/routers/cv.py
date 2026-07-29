import math
import secrets
import string
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload, joinedload

from ..database import get_db
from ..models import User, UserCV, CVVersion, Template
from ..schemas import (
    CVCreate, CVUpdate, CVResponse, CVDetailResponse, PaginatedCVResponse,
    CVVersionResponse, PublishResponse, CVPublicResponse,
)
from ..auth import get_current_user


def generate_slug(length: int = 8) -> str:
    return ''.join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(length))

router = APIRouter(prefix="/api/cv", tags=["cv"])


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
            is_published=cv.is_published,
            public_slug=cv.public_slug,
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

    cv = UserCV(
        user_id=user.id,
        template_id=template.id,
        title=data.title or template.title,
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
        is_published=cv.is_published,
        public_slug=cv.public_slug,
        template_title=cv.template.title if cv.template else None,
    )


@router.patch("/{cv_id}", response_model=CVDetailResponse)
async def update_cv(
    cv_id: int,
    data: CVUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserCV)
        .options(selectinload(UserCV.current_version), selectinload(UserCV.template))
        .where(UserCV.id == cv_id, UserCV.user_id == user.id)
    )
    cv = result.scalar_one_or_none()
    if not cv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CV not found")

    cv.title = data.title
    await db.commit()
    await db.refresh(cv)

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
        is_published=cv.is_published,
        public_slug=cv.public_slug,
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
    await db.commit()
    await db.refresh(cv)

    return CVVersionResponse.model_validate(source_version)


@router.post("/{cv_id}/publish", response_model=PublishResponse)
async def publish_cv(
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

    slug = generate_slug()
    for _ in range(10):
        existing = await db.execute(select(UserCV).where(UserCV.public_slug == slug))
        if not existing.scalar_one_or_none():
            break
        slug = generate_slug()
    else:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to generate unique slug")

    cv.is_published = True
    cv.public_slug = slug
    await db.commit()

    return PublishResponse(slug=slug, url=f"/cv/{slug}")


@router.post("/{cv_id}/unpublish")
async def unpublish_cv(
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

    cv.is_published = False
    cv.public_slug = None
    await db.commit()

    return {"ok": True}


@router.get("/p/{slug}", response_model=CVPublicResponse)
async def view_public_cv(
    slug: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserCV)
        .options(joinedload(UserCV.user), joinedload(UserCV.current_version), joinedload(UserCV.template))
        .where(UserCV.public_slug == slug, UserCV.is_published == True)
    )
    cv = result.scalar_one_or_none()
    if not cv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CV not found")

    latest_html = cv.current_version.html_content if cv.current_version else (
        cv.template.html_code if cv.template else ""
    )

    return CVPublicResponse(
        title=cv.title,
        latest_html=latest_html,
        display_name=cv.user.display_name if cv.user else "Unknown",
    )
