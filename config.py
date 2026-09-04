"""12-factor 配置加载。所有配置项都从环境变量读取,.env 文件由 python-dotenv 加载。
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env")
except Exception:  # noqa: BLE001
    pass


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _int(value: str | None, default: int) -> int:
    try:
        return int(value) if value is not None and value != "" else default
    except (TypeError, ValueError):
        return default


class Config:
    # Flask
    SECRET_KEY = os.environ.get("FLASK_SECRET_KEY") or "dev-secret-change-me"
    DEBUG = _bool(os.environ.get("FLASK_ENV"), False) or _bool(
        os.environ.get("FLASK_DEBUG"), False
    )

    # 数据库
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        "mysql+pymysql://root:root%40123@172.16.205.22:9301/panbound?charset=utf8mb4",
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 1800,
    }

    # Redis
    REDIS_URL = os.environ.get("REDIS_URL", "redis://172.16.205.22:3311/0")

    # LLM (MiniMax-M3)
    MINIMAX_API_KEY = os.environ.get("MINIMAX_API_KEY", "") or os.environ.get(
        "MINIMAX_CN_API_KEY", ""
    )
    MINIMAX_BASE_URL = os.environ.get("MINIMAX_BASE_URL", "https://api.minimax.io/v1")
    MINIMAX_MODEL = os.environ.get("MINIMAX_MODEL", "MiniMax-M3")
    MINIMAX_THINKING_LEVEL = _int(os.environ.get("MINIMAX_THINKING_LEVEL"), 2)
    REPORT_GENERATE_TIMEOUT = _int(os.environ.get("REPORT_GENERATE_TIMEOUT"), 180)

    # 初始管理员
    ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin")
    ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@panbound.local")

    # 验证码
    CAPTCHA_TTL_SECONDS = _int(os.environ.get("CAPTCHA_TTL_SECONDS"), 300)
    CAPTCHA_LENGTH = _int(os.environ.get("CAPTCHA_LENGTH"), 4)
    CAPTCHA_WIDTH = _int(os.environ.get("CAPTCHA_WIDTH"), 160)
    CAPTCHA_HEIGHT = _int(os.environ.get("CAPTCHA_HEIGHT"), 48)
    CAPTCHA_FONT_SIZE = _int(os.environ.get("CAPTCHA_FONT_SIZE"), 30)

    # 站点
    SITE_NAME = os.environ.get("SITE_NAME", "PanBound 复盘与预案")
    SITE_BASE_URL = os.environ.get("SITE_BASE_URL", "http://127.0.0.1:5000")

    # 会话
    SESSION_COOKIE_NAME = "panbound_session"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_DURATION = 60 * 60 * 24 * 7
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 8

    # 上传/正文长度
    REPORTS_RAW_CONTEXT_MAX_LEN = 16000
    REPORTS_TITLE_MAX_LEN = 200
