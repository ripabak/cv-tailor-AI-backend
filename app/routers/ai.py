import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..database import get_db
from ..models import User, UserCV, CVVersion
from ..schemas import CVGenerate, CVVersionResponse, CVDetailResponse, CVGenerateResponse
from ..auth import get_current_user
from ..config import (
    OPENROUTER_API_KEY, OPENROUTER_MODEL, OPENROUTER_BASE_URL, SYSTEM_PROMPT,
)
from ..routers.cv import extract_title

router = APIRouter(prefix="/api/cv", tags=["ai"])


async def call_openrouter(template_html: str, user_prompt: str) -> str | None:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Template HTML:\n\n{template_html}\n\nInstruksi user:\n{user_prompt}"},
    ]

    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            response = await client.post(
                f"{OPENROUTER_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": OPENROUTER_MODEL,
                    "messages": messages,
                    "temperature": 0.3,
                },
            )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            return content.strip()
        except httpx.HTTPError as e:
            print(f"OpenRouter error: {e}")
            return None


@router.post("/{cv_id}/generate", response_model=CVGenerateResponse)
async def generate_refine(
    cv_id: int,
    data: CVGenerate,
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
        .limit(1)
    )
    latest_version = versions_result.scalar_one_or_none()
    if not latest_version:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No HTML to refine")

    generated_html = await call_openrouter(latest_version.html_content, data.prompt)
    if generated_html is None:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="LLM generation failed")

    if not generated_html.strip().lower().startswith("<html"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="LLM returned invalid HTML. Please retry.",
        )

    new_title = extract_title(generated_html)
    if new_title and new_title != "Untitled CV":
        cv.title = new_title

    version = CVVersion(user_cv_id=cv.id, html_content=generated_html)
    db.add(version)
    cv.updated_at = version.created_at
    await db.commit()
    await db.refresh(version)

    cv_detail = CVDetailResponse(
        id=cv.id,
        user_id=cv.user_id,
        template_id=cv.template_id,
        title=cv.title,
        created_at=cv.created_at,
        updated_at=cv.updated_at,
        latest_html=generated_html,
        template_title=None,
    )
    return CVGenerateResponse(
        cv=cv_detail,
        version=CVVersionResponse.model_validate(version),
    )
