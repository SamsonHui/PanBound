"""管理员后台:角色 / SSO / LLM Provider / 用户。"""

from __future__ import annotations

import json
import logging
from functools import wraps

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required
from flask_wtf import FlaskForm
from sqlalchemy import desc
from wtforms import (
    BooleanField,
    FloatField,
    IntegerField,
    PasswordField,
    SelectField,
    StringField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Length, NumberRange, Optional

from ..extensions import db
from ..models.role import ROLE_GROUPS, Role
from ..models.sso import SSOProvider
from ..models.user import User
from ..llm.providers import LLMProvider as _LLMProvider

bp = Blueprint("admin", __name__, url_prefix="/admin")
logger = logging.getLogger(__name__)


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not getattr(current_user, "is_admin", False):
            abort(403)
        return view(*args, **kwargs)

    return wrapped


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------


class RoleForm(FlaskForm):
    name = StringField("name", validators=[DataRequired(), Length(min=2, max=64)])
    display_name = StringField("display_name", validators=[DataRequired(), Length(min=2, max=128)])
    role_group = SelectField("role_group", choices=ROLE_GROUPS, validators=[DataRequired()])
    description = StringField("description", validators=[Optional(), Length(max=512)])
    system_prompt = TextAreaField("system_prompt", validators=[DataRequired(), Length(min=20)])
    stance = SelectField(
        "stance", choices=[("neutral", "neutral"), ("bull", "bull"), ("bear", "bear")], default="neutral"
    )
    temperature = FloatField("temperature", default=0.4, validators=[NumberRange(min=0, max=2)])
    max_tokens = IntegerField("max_tokens", default=2048, validators=[NumberRange(min=64, max=16384)])
    sort_order = IntegerField("sort_order", default=100)
    use_thinking = BooleanField("use_thinking", default=True)
    enabled = BooleanField("enabled", default=True)


@bp.route("/")
@admin_required
def index():
    return redirect(url_for("admin.roles"))


@bp.route("/roles")
@admin_required
def roles():
    items = Role.query.order_by(Role.sort_order.asc(), Role.id.asc()).all()
    return render_template("admin/roles.html", roles=items)


@bp.route("/roles/new", methods=["GET", "POST"])
@admin_required
def role_new():
    form = RoleForm()
    if form.validate_on_submit():
        if Role.query.filter_by(name=form.name.data.strip()).first():
            flash("name 已存在。", "danger")
            return render_template("admin/role_form.html", form=form, role=None)
        role = Role(
            name=form.name.data.strip(),
            display_name=form.display_name.data.strip(),
            role_group=form.role_group.data,
            description=form.description.data or "",
            system_prompt=form.system_prompt.data,
            stance=form.stance.data,
            temperature=form.temperature.data or 0.4,
            max_tokens=form.max_tokens.data or 2048,
            sort_order=form.sort_order.data or 100,
            use_thinking=form.use_thinking.data,
            enabled=form.enabled.data,
            is_builtin=False,
        )
        db.session.add(role)
        db.session.commit()
        flash("已创建。", "info")
        return redirect(url_for("admin.roles"))
    return render_template("admin/role_form.html", form=form, role=None)


@bp.route("/roles/<int:role_id>/edit", methods=["GET", "POST"])
@admin_required
def role_edit(role_id: int):
    role = db.session.get(Role, role_id)
    if role is None:
        abort(404)
    form = RoleForm(data=role.__dict__)
    # 内置 name 不可改
    is_builtin = bool(role.is_builtin)
    if request.method == "GET":
        if is_builtin:
            form.name.render_kw = {"readonly": True}

    if form.validate_on_submit():
        if is_builtin:
            form.name.data = role.name  # 强制不变
        if (
            not is_builtin
            and Role.query.filter(Role.id != role.id, Role.name == form.name.data.strip()).first()
        ):
            flash("name 已被其他角色占用。", "danger")
            return render_template("admin/role_form.html", form=form, role=role)
        role.display_name = form.display_name.data.strip()
        role.role_group = form.role_group.data
        role.description = form.description.data or ""
        role.system_prompt = form.system_prompt.data
        role.stance = form.stance.data
        role.temperature = form.temperature.data or 0.4
        role.max_tokens = form.max_tokens.data or 2048
        role.sort_order = form.sort_order.data or 100
        role.use_thinking = form.use_thinking.data
        role.enabled = form.enabled.data
        if not is_builtin:
            role.name = form.name.data.strip()
        db.session.commit()
        flash("已保存。", "info")
        return redirect(url_for("admin.roles"))
    return render_template("admin/role_form.html", form=form, role=role)


@bp.route("/roles/<int:role_id>/toggle", methods=["POST"])
@admin_required
def role_toggle(role_id: int):
    role = db.session.get(Role, role_id)
    if role is None:
        abort(404)
    role.enabled = not role.enabled
    db.session.commit()
    flash(f"已{'启用' if role.enabled else '停用'} {role.name}。", "info")
    return redirect(url_for("admin.roles"))


@bp.route("/roles/<int:role_id>/delete", methods=["POST"])
@admin_required
def role_delete(role_id: int):
    role = db.session.get(Role, role_id)
    if role is None:
        abort(404)
    if role.is_builtin:
        flash("内置角色不可删除。", "danger")
        return redirect(url_for("admin.roles"))
    db.session.delete(role)
    db.session.commit()
    flash("已删除。", "info")
    return redirect(url_for("admin.roles"))


# ---------------------------------------------------------------------------
# SSO Providers
# ---------------------------------------------------------------------------


class SSOProviderForm(FlaskForm):
    name = StringField("name", validators=[DataRequired(), Length(min=2, max=64)])
    display_name = StringField("display_name", validators=[DataRequired(), Length(min=2, max=128)])
    provider_type = SelectField(
        "provider_type",
        choices=[
            ("oidc", "oidc"),
            ("oauth2", "oauth2"),
            ("wecom", "企业微信"),
            ("feishu", "飞书"),
            ("dingtalk", "钉钉"),
            ("generic", "generic"),
        ],
        default="oidc",
    )
    client_id = StringField("client_id", validators=[DataRequired()])
    client_secret = PasswordField("client_secret", validators=[DataRequired()])
    authorize_url = StringField("authorize_url", validators=[DataRequired(), Length(max=512)])
    token_url = StringField("token_url", validators=[DataRequired(), Length(max=512)])
    userinfo_url = StringField("userinfo_url", validators=[DataRequired(), Length(max=512)])
    scope = StringField("scope", default="openid profile email", validators=[DataRequired()])
    redirect_path = StringField("redirect_path", default="/sso/callback")
    username_field = StringField("username_field", default="preferred_username")
    email_field = StringField("email_field", default="email")
    display_name_field = StringField("display_name_field", default="name")
    subject_field = StringField("subject_field", default="sub")
    sort_order = IntegerField("sort_order", default=100)
    auto_create_user = BooleanField("auto_create_user", default=True)
    enabled = BooleanField("enabled", default=True)


@bp.route("/sso")
@admin_required
def sso_list():
    items = SSOProvider.query.order_by(SSOProvider.sort_order.asc()).all()
    return render_template("admin/sso.html", providers=items)


@bp.route("/sso/new", methods=["GET", "POST"])
@admin_required
def sso_new():
    form = SSOProviderForm()
    if form.validate_on_submit():
        if SSOProvider.query.filter_by(name=form.name.data.strip()).first():
            flash("name 已存在。", "danger")
            return render_template("admin/sso_form.html", form=form, provider=None)
        p = SSOProvider(
            name=form.name.data.strip(),
            display_name=form.display_name.data.strip(),
            provider_type=form.provider_type.data,
            client_id=form.client_id.data.strip(),
            client_secret_enc=form.client_secret.data,
            authorize_url=form.authorize_url.data.strip(),
            token_url=form.token_url.data.strip(),
            userinfo_url=form.userinfo_url.data.strip(),
            scope=form.scope.data,
            redirect_path=form.redirect_path.data or "/sso/callback",
            username_field=form.username_field.data or "preferred_username",
            email_field=form.email_field.data or "email",
            display_name_field=form.display_name_field.data or "name",
            subject_field=form.subject_field.data or "sub",
            sort_order=form.sort_order.data or 100,
            auto_create_user=form.auto_create_user.data,
            enabled=form.enabled.data,
        )
        db.session.add(p)
        db.session.commit()
        flash("已创建 SSO Provider。", "info")
        return redirect(url_for("admin.sso_list"))
    return render_template("admin/sso_form.html", form=form, provider=None)


@bp.route("/sso/<int:provider_id>/edit", methods=["GET", "POST"])
@admin_required
def sso_edit(provider_id: int):
    p = db.session.get(SSOProvider, provider_id)
    if p is None:
        abort(404)
    form = SSOProviderForm(data={
        "name": p.name,
        "display_name": p.display_name,
        "provider_type": p.provider_type,
        "client_id": p.client_id,
        "client_secret": "",
        "authorize_url": p.authorize_url,
        "token_url": p.token_url,
        "userinfo_url": p.userinfo_url,
        "scope": p.scope,
        "redirect_path": p.redirect_path,
        "username_field": p.username_field,
        "email_field": p.email_field,
        "display_name_field": p.display_name_field,
        "subject_field": p.subject_field,
        "sort_order": p.sort_order,
        "auto_create_user": p.auto_create_user,
        "enabled": p.enabled,
    })
    if form.validate_on_submit():
        p.name = form.name.data.strip()
        p.display_name = form.display_name.data.strip()
        p.provider_type = form.provider_type.data
        p.client_id = form.client_id.data.strip()
        if form.client_secret.data:
            p.client_secret_enc = form.client_secret.data
        p.authorize_url = form.authorize_url.data.strip()
        p.token_url = form.token_url.data.strip()
        p.userinfo_url = form.userinfo_url.data.strip()
        p.scope = form.scope.data
        p.redirect_path = form.redirect_path.data or "/sso/callback"
        p.username_field = form.username_field.data or "preferred_username"
        p.email_field = form.email_field.data or "email"
        p.display_name_field = form.display_name_field.data or "name"
        p.subject_field = form.subject_field.data or "sub"
        p.sort_order = form.sort_order.data or 100
        p.auto_create_user = form.auto_create_user.data
        p.enabled = form.enabled.data
        db.session.commit()
        flash("已保存。", "info")
        return redirect(url_for("admin.sso_list"))
    return render_template("admin/sso_form.html", form=form, provider=p)


@bp.route("/sso/<int:provider_id>/toggle", methods=["POST"])
@admin_required
def sso_toggle(provider_id: int):
    p = db.session.get(SSOProvider, provider_id)
    if p is None:
        abort(404)
    p.enabled = not p.enabled
    db.session.commit()
    flash(f"已{'启用' if p.enabled else '停用'} {p.name}。", "info")
    return redirect(url_for("admin.sso_list"))


@bp.route("/sso/<int:provider_id>/delete", methods=["POST"])
@admin_required
def sso_delete(provider_id: int):
    p = db.session.get(SSOProvider, provider_id)
    if p is None:
        abort(404)
    db.session.delete(p)
    db.session.commit()
    flash("已删除。", "info")
    return redirect(url_for("admin.sso_list"))


# ---------------------------------------------------------------------------
# LLM Providers
# ---------------------------------------------------------------------------


class LLMProviderForm(FlaskForm):
    name = StringField("name", validators=[DataRequired(), Length(min=2, max=64)])
    display_name = StringField("display_name", validators=[DataRequired(), Length(min=2, max=128)])
    provider_kind = SelectField(
        "provider_kind",
        choices=[("openai_compatible", "openai_compatible")],
        default="openai_compatible",
    )
    base_url = StringField("base_url", validators=[DataRequired(), Length(max=512)])
    api_key = PasswordField("api_key", validators=[DataRequired()])
    default_model = StringField("default_model", validators=[DataRequired()])
    models_json = TextAreaField("models_json (JSON 数组)", validators=[Optional()])
    extra_headers_json = TextAreaField("extra_headers_json (JSON 对象)", validators=[Optional()])
    thinking_mode = SelectField(
        "thinking_mode",
        choices=[("off", "off"), ("enabled", "enabled"), ("adaptive", "adaptive")],
        default="adaptive",
    )
    timeout = IntegerField("timeout(s)", default=180, validators=[NumberRange(min=10, max=600)])
    is_default = BooleanField("is_default", default=False)
    enabled = BooleanField("enabled", default=True)
    sort_order = IntegerField("sort_order", default=100)
    note = StringField("note", validators=[Optional(), Length(max=512)])


@bp.route("/llm-providers")
@admin_required
def llm_providers():
    items = _LLMProvider.query.order_by(_LLMProvider.sort_order.asc()).all()
    return render_template("admin/llm_providers.html", providers=items)


@bp.route("/llm-providers/new", methods=["GET", "POST"])
@admin_required
def llm_provider_new():
    form = LLMProviderForm()
    if form.validate_on_submit():
        if _LLMProvider.query.filter_by(name=form.name.data.strip()).first():
            flash("name 已存在。", "danger")
            return render_template("admin/llm_provider_form.html", form=form, provider=None)
        # 校验 JSON
        for fld in ("models_json", "extra_headers_json"):
            raw = getattr(form, fld).data
            if raw:
                try:
                    json.loads(raw)
                except Exception:
                    flash(f"{fld} 不是合法 JSON。", "danger")
                    return render_template("admin/llm_provider_form.html", form=form, provider=None)

        if form.is_default.data:
            _clear_other_defaults()

        p = _LLMProvider(
            name=form.name.data.strip(),
            display_name=form.display_name.data.strip(),
            provider_kind=form.provider_kind.data,
            base_url=form.base_url.data.strip(),
            api_key=form.api_key.data,
            default_model=form.default_model.data.strip(),
            models_json=form.models_json.data or None,
            extra_headers_json=form.extra_headers_json.data or None,
            thinking_mode=form.thinking_mode.data,
            timeout=form.timeout.data or 180,
            is_default=form.is_default.data,
            enabled=form.enabled.data,
            sort_order=form.sort_order.data or 100,
            note=form.note.data,
        )
        db.session.add(p)
        db.session.commit()
        flash("已创建 LLM Provider。", "info")
        return redirect(url_for("admin.llm_providers"))
    return render_template("admin/llm_provider_form.html", form=form, provider=None)


@bp.route("/llm-providers/<int:pid>/edit", methods=["GET", "POST"])
@admin_required
def llm_provider_edit(pid: int):
    p = db.session.get(_LLMProvider, pid)
    if p is None:
        abort(404)
    form = LLMProviderForm(data={
        "name": p.name,
        "display_name": p.display_name,
        "provider_kind": p.provider_kind,
        "base_url": p.base_url,
        "api_key": "",
        "default_model": p.default_model,
        "models_json": p.models_json,
        "extra_headers_json": p.extra_headers_json,
        "thinking_mode": p.thinking_mode,
        "timeout": p.timeout,
        "is_default": p.is_default,
        "enabled": p.enabled,
        "sort_order": p.sort_order,
        "note": p.note,
    })
    if form.validate_on_submit():
        for fld in ("models_json", "extra_headers_json"):
            raw = getattr(form, fld).data
            if raw:
                try:
                    json.loads(raw)
                except Exception:
                    flash(f"{fld} 不是合法 JSON。", "danger")
                    return render_template("admin/llm_provider_form.html", form=form, provider=p)
        if form.is_default.data:
            _clear_other_defaults(exclude_id=p.id)
        p.name = form.name.data.strip()
        p.display_name = form.display_name.data.strip()
        p.provider_kind = form.provider_kind.data
        p.base_url = form.base_url.data.strip()
        if form.api_key.data:
            p.api_key = form.api_key.data
        p.default_model = form.default_model.data.strip()
        p.models_json = form.models_json.data or None
        p.extra_headers_json = form.extra_headers_json.data or None
        p.thinking_mode = form.thinking_mode.data
        p.timeout = form.timeout.data or 180
        p.is_default = form.is_default.data
        p.enabled = form.enabled.data
        p.sort_order = form.sort_order.data or 100
        p.note = form.note.data
        db.session.commit()
        flash("已保存。", "info")
        return redirect(url_for("admin.llm_providers"))
    return render_template("admin/llm_provider_form.html", form=form, provider=p)


@bp.route("/llm-providers/<int:pid>/toggle", methods=["POST"])
@admin_required
def llm_provider_toggle(pid: int):
    p = db.session.get(_LLMProvider, pid)
    if p is None:
        abort(404)
    p.enabled = not p.enabled
    db.session.commit()
    flash(f"已{'启用' if p.enabled else '停用'} {p.name}。", "info")
    return redirect(url_for("admin.llm_providers"))


@bp.route("/llm-providers/<int:pid>/delete", methods=["POST"])
@admin_required
def llm_provider_delete(pid: int):
    p = db.session.get(_LLMProvider, pid)
    if p is None:
        abort(404)
    db.session.delete(p)
    db.session.commit()
    flash("已删除。", "info")
    return redirect(url_for("admin.llm_providers"))


def _clear_other_defaults(*, exclude_id: int | None = None) -> None:
    q = _LLMProvider.query.filter_by(is_default=True)
    if exclude_id is not None:
        q = q.filter(_LLMProvider.id != exclude_id)
    for x in q.all():
        x.is_default = False
    db.session.commit()


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


class UserEditForm(FlaskForm):
    role = SelectField(
        "role", choices=[("user", "user"), ("admin", "admin")], validators=[DataRequired()]
    )
    is_active = BooleanField("is_active", default=True)
    must_change_password = BooleanField("must_change_password", default=False)
    new_password = PasswordField("重置密码 (留空不改)", validators=[Optional(), Length(min=4, max=128)])


@bp.route("/users")
@admin_required
def users():
    items = User.query.order_by(User.id.asc()).all()
    return render_template("admin/users.html", users=items)


@bp.route("/users/<int:uid>/edit", methods=["GET", "POST"])
@admin_required
def user_edit(uid: int):
    user = db.session.get(User, uid)
    if user is None:
        abort(404)
    form = UserEditForm(data={"role": user.role, "is_active": user.is_active, "must_change_password": user.must_change_password})
    if form.validate_on_submit():
        user.role = form.role.data
        user.is_active = form.is_active.data
        user.must_change_password = form.must_change_password.data
        if form.new_password.data:
            user.set_password(form.new_password.data)
        db.session.commit()
        flash("已保存。", "info")
        return redirect(url_for("admin.users"))
    return render_template("admin/user_edit.html", form=form, user=user)


@bp.route("/users/<int:uid>/toggle", methods=["POST"])
@admin_required
def user_toggle(uid: int):
    user = db.session.get(User, uid)
    if user is None:
        abort(404)
    if user.id == current_user.id:
        flash("不能停用自己。", "warning")
        return redirect(url_for("admin.users"))
    user.is_active = not user.is_active
    db.session.commit()
    flash(f"已{'启用' if user.is_active else '停用'} {user.username}。", "info")
    return redirect(url_for("admin.users"))
