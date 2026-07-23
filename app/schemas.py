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
    created_at: datetime.datetime
    updated_at: datetime.datetime

    model_config = {"from_attributes": True}


class CVDetailResponse(CVResponse):
    latest_html: str | None = None
    template_title: str | None = None


class CVVersionResponse(BaseModel):
    id: int
    user_cv_id: int
    html_content: str
    created_at: datetime.datetime

    model_config = {"from_attributes": True}


class ChatMessage(BaseModel):
    role: str
    content: str | None = None
    tool_calls: list[dict] | None = None
    tool_call_id: str | None = None


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    session_id: str | None = None
    stream: bool = True


class MessageResponse(BaseModel):
    id: int
    role: str
    content: str | None = None
    tool_calls: dict | None = None
    tool_call_id: str | None = None
    created_at: datetime.datetime

    model_config = {"from_attributes": True}
