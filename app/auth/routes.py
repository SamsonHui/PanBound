"""登录/退出/验证码 路由。"""

from __future__ import annotations

import base64
from datetime import datetime

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from flask_wtf import FlaskForm
from wtforms import PasswordField, StringField
from wtforms.validators import DataRequired, Length

from ..extensions import db
from ..models.audit import AuditLog
from ..models.sso import SSOProvider
from ..models.user import User
from .captcha import generate_captcha, verify_captcha

bp = Blueprint("auth", __name__, url_prefix="/auth")


class LoginForm(FlaskForm):
    username = StringField("用户名", validators=[DataRequired(), Length(min=2, max=64)])
    password = PasswordField("密码", validators=[DataRequired(), Length(min=1, max=128)])
    captcha_key = StringField("captcha_key", validators=[DataRequired()])
    captcha = StringField("验证码", validators=[DataRequired(), Length(min=2, max=12)])


def _audit(action: str, user: User | None, detail: str = "") -> None:
    try:
        db.session.add(
            AuditLog(
                user_id=user.id if user else None,
                username=user.username if user else None,
                action=action,
                ip=request.headers.get("X-Forwarded-For", request.remote_addr or "")[:64],
                user_agent=(request.user_agent.string or "")[:512],
                detail=detail[:1000] if detail else None,
            )
        )
        db.session.commit()
    except Exception as exc:  # noqa: BLE001
        current_app.logger.warning("audit log failed: %s", exc)
        db.session.rollback()


def _list_enabled_providers() -> list[SSOProvider]:
    try:
        return (
            SSOProvider.query.filter_by(enabled=True)
            .order_by(SSOProvider.sort_order.asc(), SSOProvider.id.asc())
            .all()
        )
    except Exception as exc:  # noqa: BLE001
        current_app.logger.warning("查询 SSO provider 失败:%s", exc)
        return []


def _render_login(form, error_flash: str | None = None, *, fresh_captcha: bool = False):
    if error_flash:
        flash(error_flash, "danger")
    if fresh_captcha:
        captcha_key, captcha_png = generate_captcha()
    else:
        captcha_key = form.captcha_key.data or ""
        # 旧 key 可能已失效,重新生成
        captcha_key, captcha_png = generate_captcha()
    return render_template(
        "auth/login.html",
        form=form,
        captcha_key=captcha_key,
        captcha_png_b64=base64.b64encode(captcha_png).decode("ascii"),
        providers=_list_enabled_providers(),
        site_name=current_app.config["SITE_NAME"],
    )


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    form = LoginForm()

    if request.method == "GET":
        captcha_key, captcha_png = generate_captcha()
        return render_template(
            "auth/login.html",
            form=form,
            captcha_key=captcha_key,
            captcha_png_b64=base64.b64encode(captcha_png).decode("ascii"),
            providers=_list_enabled_providers(),
            site_name=current_app.config["SITE_NAME"],
        )

    # POST
    if not form.validate_on_submit():
        return _render_login(form, "请检查表单输入。", fresh_captcha=True)

    if not verify_captcha(form.captcha_key.data, form.captcha.data):
        _audit("login_failed", None, f"username={form.username.data} reason=captcha")
        return _render_login(form, "验证码错误或已过期,请重新输入。", fresh_captcha=True)

    user = User.query.filter(
        (User.username == form.username.data) | (User.email == form.username.data)
    ).first()

    if user is None or not user.check_password(form.password.data):
        _audit("login_failed", None, f"username={form.username.data} reason=password")
        return _render_login(form, "用户名或密码错误。", fresh_captcha=True)

    if not user.is_active:
        _audit("login_disabled", user, "")
        return _render_login(form, "账号已停用,请联系管理员。", fresh_captcha=True)

    user.last_login_at = datetime.utcnow()
    db.session.commit()
    login_user(user, remember=False)
    _audit("login_success", user, "")

    next_url = request.args.get("next") or url_for("dashboard")
    if not next_url.startswith("/"):
        next_url = url_for("dashboard")
    return redirect(next_url)


@bp.route("/logout")
@login_required
def logout():
    _audit("logout", current_user, "")
    logout_user()
    flash("已退出登录。", "info")
    return redirect(url_for("auth.login"))
