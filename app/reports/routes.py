"""Reports 路由:列表 / 新建 / 详情 / 重新生成 / 状态轮询。"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required
from flask_wtf import FlaskForm
from sqlalchemy import desc
from wtforms import DateField, StringField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional

from ..extensions import db
from ..models.report import Report
from ..models.role import RoleRun
from ..models.user import User
from .service import create_report, regenerate_report

bp = Blueprint("reports", __name__, url_prefix="/reports")


# ---------------------------------------------------------------------------
# 表单
# ---------------------------------------------------------------------------


class NewReportForm(FlaskForm):
    trade_date = DateField(
        "交易日",
        format="%Y-%m-%d",
        validators=[DataRequired()],
        default=date.today,
    )
    title = StringField(
        "标题",
        validators=[DataRequired(), Length(min=2, max=200)],
        default=lambda: f"复盘 {date.today().isoformat()}",
    )
    raw_context = TextAreaField(
        "盘面笔记 (raw_context,可空,留空将自动从 12 个信源拉取)",
        validators=[Optional(), Length(max=16000)],
        description="覆盖:三大指数涨跌幅/成交量/涨跌家数/连板高度/题材主线/监管动态/隔夜美股 等。",
    )


# ---------------------------------------------------------------------------
# 页面
# ---------------------------------------------------------------------------


@bp.route("/")
@login_required
def index():
    page = request.args.get("page", 1, type=int)
    per_page = 20
    q = Report.query.order_by(desc(Report.created_at))
    pagination = q.paginate(page=page, per_page=per_page, error_out=False)
    return render_template(
        "reports/index.html",
        pagination=pagination,
        reports=pagination.items,
        status_labels={
            "draft": "排队中",
            "generating": "生成中",
            "ready": "已完成",
            "failed": "失败",
        },
    )


def dashboard():
    """根路由 -> 我的最新报告概览。"""
    if not current_user.is_authenticated:
        return redirect(url_for("auth.login"))
    latest = (
        Report.query.filter_by(created_by=current_user.id)
        .order_by(desc(Report.created_at))
        .first()
    )
    recent = (
        Report.query.order_by(desc(Report.created_at)).limit(8).all()
    )
    return render_template(
        "reports/index.html",
        pagination=None,
        reports=recent,
        latest=latest,
        status_labels={
            "draft": "排队中",
            "generating": "生成中",
            "ready": "已完成",
            "failed": "失败",
        },
    )


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    form = NewReportForm()
    if request.method == "GET":
        # 用今日作为默认值
        form.trade_date.data = form.trade_date.data or date.today()
    if form.validate_on_submit():
        try:
            rpt = create_report(
                user=current_user,
                trade_date=form.trade_date.data,
                title=form.title.data,
                raw_context=form.raw_context.data,
            )
        except Exception as exc:  # noqa: BLE001
            current_app.logger.exception("create_report 失败")
            flash(f"创建报告失败:{exc}", "danger")
            return render_template("reports/new.html", form=form)
        flash("报告已创建,正在排队生成…", "info")
        return redirect(url_for("reports.detail", report_id=rpt.id))
    return render_template("reports/new.html", form=form)


@bp.route("/preview-context")
@login_required
def preview_context():
    """预览自动采集的 raw_context (不落库)。"""
    from ..collectors.aggregator import collect_and_compose

    try:
        results, text = collect_and_compose(trade_date=date.today().isoformat())
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 500
    summary = [
        {"source": r.source, "ok": r.ok, "items": len(r.data) if r.ok and hasattr(r.data, "__len__") else 0, "latency_ms": r.latency_ms, "error": r.error}
        for r in results
    ]
    return jsonify({"ok": True, "text": text, "summary": summary, "length": len(text)})


@bp.route("/<int:report_id>")
@login_required
def detail(report_id: int):
    rpt = db.session.get(Report, report_id)
    if rpt is None:
        abort(404)
    role_runs = (
        RoleRun.query.filter_by(report_id=rpt.id)
        .order_by(RoleRun.step_index.asc(), RoleRun.id.asc())
        .all()
    )
    payload = rpt.payload or {}
    return render_template(
        "reports/detail.html",
        report=rpt,
        role_runs=role_runs,
        payload=payload,
        payload_pretty=json.dumps(payload, ensure_ascii=False, indent=2) if payload else "",
    )


@bp.route("/<int:report_id>/regenerate", methods=["POST"])
@login_required
def regenerate(report_id: int):
    rpt = db.session.get(Report, report_id)
    if rpt is None:
        abort(404)
    if rpt.status == "generating":
        flash("报告正在生成中,请勿重复触发。", "warning")
        return redirect(url_for("reports.detail", report_id=rpt.id))
    try:
        regenerate_report(rpt)
    except Exception as exc:  # noqa: BLE001
        current_app.logger.exception("regenerate 失败")
        flash(f"重新生成失败:{exc}", "danger")
    else:
        flash("已重新加入生成队列。", "info")
    return redirect(url_for("reports.detail", report_id=rpt.id))


@bp.route("/<int:report_id>/status.json")
@login_required
def status_json(report_id: int):
    rpt = db.session.get(Report, report_id)
    if rpt is None:
        return jsonify({"error": "not_found"}), 404
    runs = (
        RoleRun.query.filter_by(report_id=rpt.id)
        .order_by(RoleRun.step_index.asc(), RoleRun.id.asc())
        .all()
    )
    return jsonify(
        {
            "id": rpt.id,
            "status": rpt.status,
            "error": rpt.error_message,
            "duration_ms": rpt.duration_ms,
            "updated_at": rpt.updated_at.isoformat() if rpt.updated_at else None,
            "role_runs": [
                {
                    "id": r.id,
                    "step_index": r.step_index,
                    "role_name": r.role_name_snapshot,
                    "status": r.status,
                    "duration_ms": r.duration_ms,
                    "model": r.model_used,
                }
                for r in runs
            ],
        }
    )
