"""报告业务层:create_report / regenerate_report。

创建/重置后,把生成任务丢到后台线程,避免阻塞 HTTP 请求。
"""

from __future__ import annotations

import logging
import threading
from datetime import date, datetime
from typing import Any

from flask import current_app
from sqlalchemy.exc import SQLAlchemyError

from ..extensions import db
from ..models.report import Report
from ..models.user import User
from .orchestrator import run_report

logger = logging.getLogger(__name__)


def _kick_off(report_id: int) -> None:
    """从请求上下文外起一个线程跑 orchestrator。"""
    try:
        app = current_app._get_current_object()  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover - 没有 app context 时
        logger.exception("kick_off 失败:无法获取 current_app")
        return

    def _runner():
        try:
            run_report(app, report_id)
        except Exception:  # noqa: BLE001
            logger.exception("后台跑 report %s 异常", report_id)

    t = threading.Thread(target=_runner, name=f"report-{report_id}", daemon=True)
    t.start()


def create_report(
    user: User,
    trade_date: date,
    title: str,
    raw_context: str,
) -> Report:
    """创建报告并异步触发生成。

    若 raw_context 不足(短于 80 字符或显式置空),自动调用 collectors 拉取实时数据填入。
    """
    final_context = (raw_context or "").strip()
    auto_filled = False
    if len(final_context) < 80:
        try:
            from ..collectors.aggregator import collect_and_compose

            _results, auto_text = collect_and_compose(trade_date=trade_date.isoformat())
            final_context = auto_text
            auto_filled = True
            logger.info("report 自动采集 %d 字符 raw_context", len(auto_text))
        except Exception:  # noqa: BLE001
            logger.exception("自动采集失败,使用用户原文")

    report = Report(
        trade_date=trade_date,
        title=title.strip(),
        raw_context=final_context,
        status="draft",
        created_by=user.id if user else None,
    )
    db.session.add(report)
    db.session.commit()
    db.session.refresh(report)

    if auto_filled:
        report.raw_context = "[auto-collected]\n" + report.raw_context
        db.session.commit()

    _kick_off(report.id)
    return report


def regenerate_report(report: Report) -> Report:
    """重置 status + 清空 RoleRun,再异步触发。"""
    from ..models.role import RoleRun

    RoleRun.query.filter_by(report_id=report.id).delete()
    report.status = "draft"
    report.error_message = None
    report.payload = None
    report.duration_ms = None
    report.updated_at = datetime.utcnow()
    db.session.commit()

    _kick_off(report.id)
    return report


def fetch_report_or_404(report_id: int) -> Report | None:
    return db.session.get(Report, report_id)
