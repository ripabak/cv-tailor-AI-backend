import datetime
from pydantic import BaseModel, EmailStr


class UserRegister(BaseModel):
    email: EmailStr
    display_name: str
    password: str


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: int
    email: str
    display_name: str
    created_at: datetime.datetime

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class TemplateResponse(BaseModel):
    id: int
    title: str
    html_code: str
    is_published: bool
    created_at: datetime.datetime

    model_config = {"from_attributes": True}


class CVCreate(BaseModel):
    template_id: int


class CVResponse(BaseModel):
    id: int
    user_id: int
    template_id: int
    title: str
    current_version_id: int | None = None
    latest_html: str | None = None
    is_published: bool = False
    public_slug: str | None = None
    created_at: datetime.datetime
    updated_at: datetime.datetime

    model_config = {"from_attributes": True}


class PaginatedCVResponse(BaseModel):
    items: list[CVResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class CVDetailResponse(CVResponse):
    template_title: str | None = None


class CVVersionResponse(BaseModel):
    id: int
    user_cv_id: int
    html_content: str
    parent_version_id: int | None = None
    created_at: datetime.datetime

    model_config = {"from_attributes": True}


class PaginatedTemplateResponse(BaseModel):
    items: list[TemplateResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class PublishResponse(BaseModel):
    slug: str
    url: str


class CVPublicResponse(BaseModel):
    title: str
    latest_html: str
    display_name: str
