"""模型聚合:把分散的模型模块聚合到 app.models 包,使 SQLAlchemy 能发现它们。"""

from __future__ import annotations

from .audit import AuditLog  # noqa: F401
from .report import Report  # noqa: F401
from .role import Role, RoleRun  # noqa: F401
from .sso import SSOLink, SSOProvider  # noqa: F401
from .user import User  # noqa: F401

__all__ = [
    "AuditLog",
    "Report",
    "Role",
    "RoleRun",
    "SSOLink",
    "SSOProvider",
    "User",
]
