import datetime
from sqlalchemy import Integer, String, Text, Boolean, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class User(Base):
    __tablename__ = "user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    cvs: Mapped[list["UserCV"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Template(Base):
    __tablename__ = "template"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    html_code: Mapped[str] = mapped_column(Text, nullable=False)
    creator_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("user.id"), nullable=True
    )
    is_published: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class UserCV(Base):
    __tablename__ = "user_cv"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("user.id"), nullable=False)
    template_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("template.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    current_version_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("cv_version.id"), nullable=True
    )
    is_published: Mapped[bool] = mapped_column(Boolean, default=False)
    public_slug: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="cvs")
    template: Mapped["Template"] = relationship()
    versions: Mapped[list["CVVersion"]] = relationship(
        back_populates="cv", cascade="all, delete-orphan", order_by="CVVersion.created_at.desc()",
        foreign_keys="[CVVersion.user_cv_id]"
    )
    current_version: Mapped["CVVersion | None"] = relationship(
        foreign_keys=[current_version_id], post_update=True
    )


class CVVersion(Base):
    __tablename__ = "cv_version"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_cv_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("user_cv.id", ondelete="CASCADE"), nullable=False
    )
    html_content: Mapped[str] = mapped_column(Text, nullable=False)
    parent_version_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("cv_version.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now()
    )

    cv: Mapped["UserCV"] = relationship(back_populates="versions", foreign_keys=[user_cv_id])
