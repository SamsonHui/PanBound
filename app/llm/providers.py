"""LLM Provider 模型 — 支持中转站/官方多种接入方式。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..extensions import db


class LLMProvider(db.Model):
    """一个可用的 LLM 端点 (官方/MiniMax官方/中转站/OpenAI 兼容服务)。"""

    __tablename__ = "llm_providers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    provider_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="openai_compatible")
    # openai_compatible / anthropic_messages / custom
    base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    api_key: Mapped[str] = mapped_column(String(512), nullable=False)
    default_model: Mapped[str] = mapped_column(String(128), nullable=False)
    # 可用模型列表 (JSON 字符串)
    models_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 自定义请求头 (JSON, 例如 {"X-API-Key": "xxx", "X-Org-Id": "xxx"})
    extra_headers_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 思考模式:off / enabled / adaptive
    thinking_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="adaptive")
    # 是否默认 (全局默认)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    timeout: Mapped[int] = mapped_column(Integer, nullable=False, default=180)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    note: Mapped[str | None] = mapped_column(String(512), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def models_list(self) -> list[str]:
        import json

        if not self.models_json:
            return [self.default_model]
        try:
            data = json.loads(self.models_json)
            if isinstance(data, list):
                return [str(x) for x in data]
        except Exception:
            pass
        return [self.default_model]

    def extra_headers(self) -> dict[str, str]:
        import json

        if not self.extra_headers_json:
            return {}
        try:
            data = json.loads(self.extra_headers_json)
            if isinstance(data, dict):
                return {str(k): str(v) for k, v in data.items()}
        except Exception:
            pass
        return {}
