"""Flask 扩展实例。所有扩展在这里创建单例,避免循环引用。
"""

from __future__ import annotations

import logging

import redis
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect

logger = logging.getLogger(__name__)

db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()

# Redis 客户端懒加载(配置加载完才连)
_redis_client: redis.Redis | None = None


def init_redis(app) -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(
            app.config["REDIS_URL"],
            decode_responses=True,
            socket_timeout=5,
            socket_connect_timeout=3,
        )
    return _redis_client


def get_redis() -> redis.Redis:
    if _redis_client is None:
        raise RuntimeError("Redis client not initialized. Call init_redis(app) first.")
    return _redis_client


login_manager.login_view = "auth.login"
login_manager.login_message = "请先登录后再访问该页面。"
login_manager.login_message_category = "warning"
login_manager.session_protection = "strong"
