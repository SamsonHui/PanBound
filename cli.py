"""Flask CLI 命令:init-db / create-admin / seed-roles / seed-default-llm-provider / list-*."""

from __future__ import annotations

import json
import sys

import click
from flask import current_app
from flask.cli import with_appcontext
from sqlalchemy import inspect

from app.extensions import db


@click.command("init-db")
@with_appcontext
def init_db():
    """创建所有表。"""
    db.create_all()
    tables = inspect(db.engine).get_table_names()
    click.echo(f"已创建 {len(tables)} 张表:")
    for t in sorted(tables):
        click.echo(f"  - {t}")


@click.command("drop-db")
@with_appcontext
def drop_db():
    """删除所有表 (危险)。"""
    if not click.confirm("将删除所有表,确认?", default=False):
        return
    db.drop_all()
    click.echo("已 drop_all().")


@click.command("create-admin")
@click.option("--username", default=None)
@click.option("--password", default=None)
@click.option("--email", default=None)
@with_appcontext
def create_admin(username, password, email):
    """创建初始管理员 (env: ADMIN_USERNAME / ADMIN_PASSWORD / ADMIN_EMAIL)。"""
    from app.models.user import User

    username = username or current_app.config["ADMIN_USERNAME"]
    password = password or current_app.config["ADMIN_PASSWORD"]
    email = email or current_app.config["ADMIN_EMAIL"]

    existing = User.query.filter_by(username=username).first()
    if existing:
        existing.role = "admin"
        existing.is_active = True
        existing.set_password(password)
        db.session.commit()
        click.echo(f"已更新管理员:{username} (id={existing.id})")
        return

    user = User(username=username, email=email, role="admin", is_active=True)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    click.echo(f"已创建管理员:{username} (id={user.id})")


@click.command("seed-roles")
@with_appcontext
def seed_roles():
    """把 seed_roles.all_builtin_roles() 写入数据库 (按 name upsert)。"""
    from app.models.role import Role
    from app.reports.seed_roles import all_builtin_roles

    n_created = 0
    n_updated = 0
    for spec in all_builtin_roles():
        role = Role.query.filter_by(name=spec["name"]).first()
        if role is None:
            role = Role(name=spec["name"], is_builtin=True)
            db.session.add(role)
            n_created += 1
        else:
            n_updated += 1
        for k, v in spec.items():
            setattr(role, k, v)
        role.is_builtin = True  # 内置标志永远为 True
    db.session.commit()
    click.echo(f"内置角色完成: 新建 {n_created}, 更新 {n_updated}, 共 {len(all_builtin_roles())} 个。")


@click.command("seed-default-llm-provider")
@with_appcontext
def seed_default_llm_provider():
    """从 env 读 MiniMax/MiniMax 配置,建一个默认 LLM Provider (若尚无默认)。"""
    from app.llm.providers import LLMProvider

    api_key = current_app.config["MINIMAX_API_KEY"]
    if not api_key:
        click.echo("MINIMAX_API_KEY 未配置,跳过。", err=True)
        sys.exit(1)

    base_url = current_app.config["MINIMAX_BASE_URL"]
    model = current_app.config["MINIMAX_MODEL"]

    has_default = LLMProvider.query.filter_by(is_default=True).first()
    if has_default:
        click.echo(f"已有默认 Provider ({has_default.name}),跳过。")
        return

    p = LLMProvider(
        name="minimax_default",
        display_name=f"MiniMax-M3 ({model})",
        provider_kind="openai_compatible",
        base_url=base_url,
        api_key=api_key,
        default_model=model,
        models_json=json.dumps([model], ensure_ascii=False),
        extra_headers_json=None,
        thinking_mode="adaptive",
        is_default=True,
        enabled=True,
        sort_order=10,
        timeout=current_app.config.get("REPORT_GENERATE_TIMEOUT", 180),
        note="由 seed-default-llm-provider 创建",
    )
    db.session.add(p)
    db.session.commit()
    click.echo(f"已创建默认 Provider: {p.name} (id={p.id})")


# ---------------------------------------------------------------------------
# 调试列表
# ---------------------------------------------------------------------------


@click.command("list-roles")
@with_appcontext
def list_roles():
    from app.models.role import Role

    for r in Role.query.order_by(Role.sort_order.asc()).all():
        click.echo(
            f"{r.sort_order:>4} [{r.role_group:>8}] {'ON ' if r.enabled else 'OFF'} "
            f"{r.name:<24} {r.display_name}"
        )


@click.command("list-users")
@with_appcontext
def list_users():
    from app.models.user import User

    for u in User.query.order_by(User.id.asc()).all():
        click.echo(f"#{u.id:<4} {u.username:<24} role={u.role:<6} active={u.is_active} email={u.email or '-'}")


@click.command("list-sso")
@with_appcontext
def list_sso():
    from app.models.sso import SSOProvider

    for p in SSOProvider.query.order_by(SSOProvider.sort_order.asc()).all():
        click.echo(
            f"#{p.id:<4} {p.name:<24} {'ON ' if p.enabled else 'OFF'} type={p.provider_type:<8} {p.display_name}"
        )


@click.command("list-providers")
@with_appcontext
def list_providers():
    from app.llm.providers import LLMProvider

    for p in LLMProvider.query.order_by(LLMProvider.sort_order.asc()).all():
        click.echo(
            f"#{p.id:<4} {'DEF' if p.is_default else '   '} {'ON ' if p.enabled else 'OFF'} "
            f"{p.name:<24} model={p.default_model:<16} base={p.base_url}"
        )


def register_cli(app):
    app.cli.add_command(init_db)
    app.cli.add_command(drop_db)
    app.cli.add_command(create_admin)
    app.cli.add_command(seed_roles)
    app.cli.add_command(seed_default_llm_provider)
    app.cli.add_command(list_roles)
    app.cli.add_command(list_users)
    app.cli.add_command(list_sso)
    app.cli.add_command(list_providers)