"""
OAuth 账户关联模型

存储用户与 OAuth 提供商（GitHub、Google、自定义 OIDC 等）的绑定关系。
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin

if TYPE_CHECKING:
    from app.models.auth import AuthUser  # pragma: no cover


def _generate_uuid() -> str:
    """生成 UUID 字符串"""
    return str(uuid.uuid4())


class OAuthAccount(Base, TimestampMixin):
    """
    OAuth 账户关联表。

    存储用户与第三方 OAuth 提供商的绑定关系，支持：
    - 内置提供商：GitHub、Google 等
    - 自定义 OIDC 提供商：Keycloak、Authentik 等

    一个用户可以绑定多个 OAuth 账户（不同提供商）。
    一个 OAuth 账户只能绑定一个用户。
    """

    __tablename__ = "oauth_account"
    __table_args__ = (
        # 确保同一提供商的同一账户只能绑定一个用户
        Index("ix_oauth_account_provider_account", "provider", "provider_account_id", unique=True),
        # 加速按用户查询
        Index("ix_oauth_account_user_id", "user_id"),
    )

    id: Mapped[str] = mapped_column(
        String(255),
        primary_key=True,
        default=_generate_uuid,
    )

    # 关联的用户 ID
    user_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
    )

    # OAuth 提供商标识（如 "github", "google", "keycloak"）
    provider: Mapped[str] = mapped_column(String(50), nullable=False)

    # 提供商返回的用户唯一标识（如 GitHub 的 user id）
    provider_account_id: Mapped[str] = mapped_column(String(255), nullable=False)

    # OAuth 返回的邮箱（可选，某些提供商可能不返回）
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # OAuth tokens（加密存储，用于后续 API 调用）
    # 注意：access_token 和 refresh_token 应使用 CredentialEncryption 加密
    access_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    refresh_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # 原始用户信息（JSON 格式，用于调试和扩展）
    raw_userinfo: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    # 关系
    user: Mapped["AuthUser"] = relationship("AuthUser", back_populates="oauth_accounts")

    def __repr__(self) -> str:
        return f"<OAuthAccount(id={self.id}, provider={self.provider}, user_id={self.user_id})>"
