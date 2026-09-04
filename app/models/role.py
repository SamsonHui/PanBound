"""平台角色 (Agent) 模型。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..extensions import db


ROLE_GROUP_INPUT = "input"
ROLE_GROUP_ANALYSIS = "analysis"
ROLE_GROUP_DEBATE = "debate"
ROLE_GROUP_RISK = "risk"
ROLE_GROUP_TRADER = "trader"

ROLE_GROUPS = [
    (ROLE_GROUP_INPUT, "数据输入"),
    (ROLE_GROUP_ANALYSIS, "多维分析"),
    (ROLE_GROUP_DEBATE, "多空辩论"),
    (ROLE_GROUP_RISK, "风控"),
    (ROLE_GROUP_TRADER, "主操盘"),
]


class Role(db.Model):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    role_group: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    input_template: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_schema: Mapped[str | None] = mapped_column(Text, nullable=True)
    stance: Mapped[str] = mapped_column(String(16), nullable=False, default="neutral")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    use_thinking: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    temperature: Mapped[float] = mapped_column(nullable=False, default=0.4)
    max_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=2048)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    runs = relationship("RoleRun", back_populates="role", cascade="all, delete-orphan")

    @property
    def label(self) -> str:
        return f"{self.display_name} [{self.name}]"


class RoleRun(db.Model):
    """一次报告里某个角色的执行记录。"""

    __tablename__ = "role_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("reports.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("roles.id", ondelete="SET NULL"), nullable=True
    )
    role_name_snapshot: Mapped[str] = mapped_column(String(64), nullable=False)
    role_group_snapshot: Mapped[str] = mapped_column(String(32), nullable=False)
    prompt_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    input_payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model_used: Mapped[str | None] = mapped_column(String(64), nullable=True)
    step_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    report = relationship("Report", back_populates="role_runs")
    role = relationship("Role", back_populates="runs")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<RoleRun {self.id} report={self.report_id} role={self.role_name_snapshot}>"
