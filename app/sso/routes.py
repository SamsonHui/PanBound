"""SSO 路由:/sso/login/<id> -> 重定向到 IdP,/sso/callback -> 处理回调。"""

from __future__ import annotations

import logging
from datetime import datetime

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import login_user

from ..extensions import db
from ..models.audit import AuditLog
from ..models.sso import SSOLink, SSOProvider
from ..models.user import User
from .oidc import (
    OIDCError,
    build_authorize_url,
    consume_state,
    exchange_code,
    extract_user_fields,
    fetch_userinfo,
    generate_state,
)

bp = Blueprint("sso", __name__)
logger = logging.getLogger(__name__)


def _decode_secret(enc: str) -> str:
    """客户端密钥目前是明文存储(单机内部使用),后续可替换为 KMS。"""
    return enc or ""


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
        logger.warning("audit 失败:%s", exc)
        db.session.rollback()


@bp.route("/login/<int:provider_id>")
def login(provider_id: int):
    provider = db.session.get(SSOProvider, provider_id)
    if provider is None or not provider.enabled:
        flash("该 SSO Provider 不存在或已停用。", "danger")
        return redirect(url_for("auth.login"))

    next_url = request.args.get("next") or "/"
    if not next_url.startswith("/"):
        next_url = "/"

    state = generate_state(provider.id, next_url=next_url)
    base = current_app.config["SITE_BASE_URL"].rstrip("/")
    redirect_uri = base + provider.redirect_path
    try:
        authorize_url = build_authorize_url(
            authorize_url=provider.authorize_url,
            client_id=provider.client_id,
            redirect_uri=redirect_uri,
            scope=provider.scope,
            state=state,
        )
    except Exception as exc:
        current_app.logger.exception("build_authorize_url 失败")
        flash(f"无法构造授权地址:{exc}", "danger")
        return redirect(url_for("auth.login"))

    return redirect(authorize_url)


@bp.route("/callback", methods=["GET"])
def callback():
    code = request.args.get("code")
    state = request.args.get("state")
    error = request.args.get("error")
    if error:
        flash(f"SSO 拒绝:{error} {request.args.get('error_description', '')}", "danger")
        return redirect(url_for("auth.login"))
    if not code or not state:
        flash("SSO 回调缺少 code 或 state。", "danger")
        return redirect(url_for("auth.login"))

    payload = consume_state(state)
    if not payload:
        flash("SSO state 无效或已过期,请重试。", "danger")
        return redirect(url_for("auth.login"))

    provider = db.session.get(SSOProvider, payload.get("provider_id"))
    if provider is None or not provider.enabled:
        flash("SSO Provider 不存在或已停用。", "danger")
        return redirect(url_for("auth.login"))

    base = current_app.config["SITE_BASE_URL"].rstrip("/")
    redirect_uri = base + provider.redirect_path

    try:
        token_data = exchange_code(
            token_url=provider.token_url,
            client_id=provider.client_id,
            client_secret=_decode_secret(provider.client_secret_enc),
            code=code,
            redirect_uri=redirect_uri,
        )
    except OIDCError as exc:
        current_app.logger.warning("OIDC token 失败:%s", exc)
        flash(f"SSO 换取 token 失败:{exc}", "danger")
        return redirect(url_for("auth.login"))

    access_token = token_data.get("access_token")
    if not access_token:
        flash("SSO 未返回 access_token。", "danger")
        return redirect(url_for("auth.login"))

    try:
        userinfo = fetch_userinfo(
            userinfo_url=provider.userinfo_url,
            access_token=access_token,
        )
    except OIDCError as exc:
        current_app.logger.warning("OIDC userinfo 失败:%s", exc)
        flash(f"SSO 获取用户信息失败:{exc}", "danger")
        return redirect(url_for("auth.login"))

    fields = extract_user_fields(userinfo, provider)
    subject = fields["subject"]
    username = fields["username"] or subject
    email = fields["email"]
    display_name = fields["display_name"]

    if not subject:
        flash("SSO 用户缺少 subject 字段。", "danger")
        return redirect(url_for("auth.login"))

    # 查 link -> user
    link = SSOLink.query.filter_by(provider_id=provider.id, external_subject=subject).first()
    user = link.user if link else None
    if user is None:
        if not provider.auto_create_user:
            flash("该 SSO 用户尚未关联本地账号,请联系管理员。", "danger")
            return redirect(url_for("auth.login"))
        # 自动创建用户
        base_username = (username or subject)[:60]
        candidate = base_username
        suffix = 1
        while User.query.filter_by(username=candidate).first() is not None:
            suffix += 1
            candidate = f"{base_username}_{suffix}"
            if suffix > 100:
                candidate = base_username + "_" + subject[:8]
                break
        user = User(
            username=candidate,
            email=email,
            display_name=display_name,
            password_hash=None,
            role="user",
            is_active=True,
        )
        db.session.add(user)
        db.session.flush()
        link = SSOLink(
            user_id=user.id,
            provider_id=provider.id,
            external_subject=subject,
            external_email=email,
            external_display_name=display_name,
        )
        db.session.add(link)
        db.session.commit()
        _audit("sso_auto_create", user, f"provider={provider.name}")
    else:
        # 更新 link
        link.last_used_at = datetime.utcnow()
        link.external_email = email or link.external_email
        link.external_display_name = display_name or link.external_display_name
        if display_name and not user.display_name:
            user.display_name = display_name
        db.session.commit()

    if not user.is_active:
        flash("账号已停用。", "danger")
        return redirect(url_for("auth.login"))

    user.last_login_at = datetime.utcnow()
    db.session.commit()
    login_user(user, remember=False)
    _audit("sso_login", user, f"provider={provider.name}")

    next_url = payload.get("next") or "/"
    if not next_url.startswith("/"):
        next_url = "/"
    return redirect(next_url)
