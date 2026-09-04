"""SSO Provider / Link 模型。

SSOProvider 是一条可启用的第三方登录源(OIDC/OAuth2),
SSOLink 是 用户 ↔ Provider 上 subject 的多对一映射。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.mysql import JSON as MySQLJSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..extensions import db


class SSOProvider(db.Model):
    __tablename__ = "sso_providers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(16), nullable=False, default="oidc")
    # oidc / oauth2 / wecom / feishu / dingtalk / generic

    client_id: Mapped[str] = mapped_column(String(255), nullable=False)
    client_secret_enc: Mapped[str] = mapped_column(Text, nullable=False)

    authorize_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    token_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    userinfo_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    scope: Mapped[str] = mapped_column(String(255), nullable=False, default="openid profile email")
    redirect_path: Mapped[str] = mapped_column(String(255), nullable=False, default="/sso/callback")

    # 从 userinfo 取本地字段的映射
    username_field: Mapped[str] = mapped_column(String(64), nullable=False, default="preferred_username")
    email_field: Mapped[str] = mapped_column(String(64), nullable=False, default="email")
    display_name_field: Mapped[str] = mapped_column(String(64), nullable=False, default="name")
    subject_field: Mapped[str] = mapped_column(String(64), nullable=False, default="sub")

    extra: Mapped[dict | None] = mapped_column(MySQLJSON, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    auto_create_user: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    links = relationship("SSOLink", back_populates="provider", cascade="all, delete-orphan")

    @property
    def is_oidc(self) -> bool:
        return self.provider_type in {"oidc", "oauth2", "generic", "wecom", "feishu", "dingtalk"}


class SSOLink(db.Model):
    __tablename__ = "sso_links"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sso_providers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    external_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    external_display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user = relationship("User", back_populates="sso_links")
    provider = relationship("SSOProvider", back_populates="links")

    __table_args__ = (
        db.UniqueConstraint("provider_id", "external_subject", name="uq_provider_subject"),
    )
