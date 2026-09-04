"""应用工厂。"""

from __future__ import annotations

import logging
from pathlib import Path

from flask import Flask, render_template
from werkzeug.middleware.proxy_fix import ProxyFix

from config import Config

from .extensions import csrf, db, init_redis, login_manager


def create_app(config_class: type = Config) -> Flask:
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    app.config.from_object(config_class)

    # 让 reverse proxy 后的 X-Forwarded-* 生效
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    logging.basicConfig(
        level=logging.DEBUG if app.config["DEBUG"] else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # 扩展
    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    try:
        init_redis(app)
    except Exception as exc:  # noqa: BLE001
        app.logger.warning("Redis 初始化失败,验证码和限流将不可用: %s", exc)

    # 模型 + 用户加载器
    from .models import audit, report, role, sso, user  # noqa: F401
    from .llm import providers as _providers  # noqa: F401

    @login_manager.user_loader
    def _load_user(user_id: str):  # pragma: no cover
        return db.session.get(user.User, int(user_id))

    # 蓝图
    from .auth.routes import bp as auth_bp
    from .sso.routes import bp as sso_bp
    from .reports.routes import bp as reports_bp
    from .admin.routes import bp as admin_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(sso_bp, url_prefix="/sso")
    app.register_blueprint(reports_bp, url_prefix="/reports")
    app.register_blueprint(admin_bp, url_prefix="/admin")

    # 根路由
    from .reports.routes import dashboard

    app.add_url_rule("/", endpoint="dashboard", view_func=dashboard)

    # 错误页
    @app.errorhandler(403)
    def _403(_e):  # pragma: no cover
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def _404(_e):  # pragma: no cover
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def _500(_e):  # pragma: no cover
        return render_template("errors/500.html"), 500

    # 全局上下文
    @app.context_processor
    def _ctx():
        enabled_sso = []
        try:
            enabled_sso = sso.SSOProvider.query.filter_by(enabled=True).all()
        except Exception:  # noqa: BLE001
            enabled_sso = []
        return {
            "site_name": app.config["SITE_NAME"],
            "enabled_sso_providers": enabled_sso,
            "current_user_obj": None,  # 走 flask_login 的 current_user
        }

    @app.template_filter("datetime")
    def _fmt_dt(value):
        if value is None:
            return ""
        return value.strftime("%Y-%m-%d %H:%M")

    @app.template_filter("date")
    def _fmt_date(value):
        if value is None:
            return ""
        return value.strftime("%Y-%m-%d")

    return app
