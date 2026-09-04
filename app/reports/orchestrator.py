"""多角色报告编排引擎。

按 sort_order 顺序跑所有 enabled=True 的 Role:
- data_validator 拿到原始 raw_context
- 其后角色拿到 raw_context + 之前所有 RoleRun 的 output_payload
- bear_researcher 还会显式收到 bull_researcher 的输出
- head_trader 的输出作为 Report.payload

所有 LLM 调用都在调用方提供的 app_context() 内执行。
"""

from __future__ import annotations

import json
import logging
import re
import time
import traceback
from datetime import datetime
from typing import Any

from flask import Flask

from ..extensions import db
from ..llm.minimax import LLMError
from ..llm.providers import LLMProvider
from ..models.report import Report
from ..models.role import Role, RoleRun

logger = logging.getLogger(__name__)

# 仅靠 JSON 自动修复仍不能解析时,退化为本地包装
_FALLBACK_WRAP = '{"_parse_error": true, "raw_text": %s}'


def _strip_json_fence(text: str) -> str:
    """去掉 ```json ... ``` 之类包装,只留 JSON。"""
    if not text:
        return ""
    s = text.strip()
    # 去开头代码块标记
    s = re.sub(r"^```(?:json|JSON)?\s*\n?", "", s)
    s = re.sub(r"\n?```\s*$", "", s)
    return s.strip()


def _safe_parse_json(text: str) -> tuple[Any | None, str]:
    """尝试从文本中提取合法 JSON。

    返回 (parsed, cleaned_text)。
    parsed 为 None 表示失败。
    """
    cleaned = _strip_json_fence(text)
    if not cleaned:
        return None, cleaned

    # 1) 直接整体解析
    try:
        return json.loads(cleaned), cleaned
    except Exception:
        pass

    # 2) 抓第一个 { ... } 或 [ ... ] 块
    for opener, closer in (("{", "}"), ("[", "]")):
        first = cleaned.find(opener)
        last = cleaned.rfind(closer)
        if first != -1 and last != -1 and last > first:
            candidate = cleaned[first : last + 1]
            try:
                return json.loads(candidate), candidate
            except Exception:
                continue

    return None, cleaned


def _select_default_provider() -> LLMProvider | None:
    return (
        LLMProvider.query.filter_by(is_default=True, enabled=True).order_by(LLMProvider.id.asc()).first()
        or LLMProvider.query.filter_by(enabled=True).order_by(LLMProvider.id.asc()).first()
    )


def _build_client_for_role(role: Role, fallback_provider: LLMProvider | None):
    """为某个 Role 构造 LLM 客户端。简单实现:用默认 Provider。"""
    from ..llm.minimax import MiniMaxClient

    if fallback_provider is None:
        raise LLMError("没有任何可用的 LLM Provider,请先在 /admin/llm-providers 配置一个。")

    return (
        MiniMaxClient(
            api_key=fallback_provider.api_key,
            base_url=fallback_provider.base_url,
            model=fallback_provider.default_model,
            thinking_level=2 if fallback_provider.thinking_mode in ("enabled", "adaptive") and role.use_thinking else 0,
            timeout=fallback_provider.timeout,
        ),
        fallback_provider,
        fallback_provider.extra_headers(),
    )


def _build_input_for_role(
    role: Role,
    report: Report,
    prior_runs: list[RoleRun],
) -> str:
    """构造 Role 的 user 输入。

    原始 raw_context + 之前所有 RoleRun 的输出 (按 step_index 排序)。
    """
    parts: list[str] = []
    parts.append(f"# trade_date\n{report.trade_date.isoformat() if report.trade_date else ''}")
    parts.append(f"# report title\n{report.title}")
    parts.append("# raw_context (用户盘面笔记)\n")
    parts.append(report.raw_context or "(空)")

    if prior_runs:
        parts.append("\n# prior role outputs (json)\n")
        for r in prior_runs:
            if not r.output_payload:
                continue
            parts.append(
                f"## {r.role_name_snapshot} [{r.role_group_snapshot}]\n{r.output_payload}\n"
            )

    # bear_researcher 强制拿到 bull 输出 (辩论)
    if role.name == "bear_researcher":
        bull = next((r for r in prior_runs if r.role_name_snapshot == "bull_researcher"), None)
        if bull and bull.output_payload:
            parts.append("\n# bull_researcher rebuttal target\n")
            parts.append(bull.output_payload)

    return "\n".join(parts)


def _save_run(run: RoleRun, *, commit: bool = True) -> None:
    db.session.add(run)
    if commit:
        db.session.commit()


def run_report(app: Flask, report_id: int) -> None:
    """在 app context 内跑完一份报告。

    这是入口,service 层会在线程中调用它。
    """
    with app.app_context():
        report: Report | None = db.session.get(Report, report_id)
        if report is None:
            logger.error("run_report: report %s 不存在", report_id)
            return

        started = time.time()
        report.status = "generating"
        report.error_message = None
        report.duration_ms = None
        report.payload = None
        # 删掉旧的 RoleRun
        RoleRun.query.filter_by(report_id=report.id).delete()
        db.session.commit()

        try:
            _do_run(report)
            elapsed = int((time.time() - started) * 1000)
            report.status = "ready"
            report.duration_ms = elapsed
            report.error_message = None
            db.session.commit()
            logger.info("report %s 生成完成,耗时 %sms", report.id, elapsed)
        except Exception as exc:  # noqa: BLE001
            logger.exception("report %s 生成失败", report.id)
            report.status = "failed"
            report.error_message = (str(exc) or exc.__class__.__name__)[:2000]
            db.session.commit()


def _do_run(report: Report) -> None:
    roles: list[Role] = (
        Role.query.filter_by(enabled=True)
        .order_by(Role.sort_order.asc(), Role.id.asc())
        .all()
    )
    if not roles:
        raise RuntimeError("没有任何启用的 Role,无法生成报告。请先 seed-roles。")

    provider = _select_default_provider()
    if provider is None:
        raise RuntimeError(
            "没有任何启用的 LLM Provider。请先 seed-default-llm-provider 或在 /admin/llm-providers 配置。"
        )

    # head_trader 必须存在,否则无法聚合
    head_role = next((r for r in roles if r.role_group == "trader"), None)
    if head_role is None:
        raise RuntimeError("未找到 role_group=trader 的最终角色 (head_trader)。")

    completed_runs: list[RoleRun] = []

    for idx, role in enumerate(roles):
        run = RoleRun(
            report_id=report.id,
            role_id=role.id,
            role_name_snapshot=role.name,
            role_group_snapshot=role.role_group,
            prompt_snapshot=role.system_prompt,
            input_payload=None,
            output_payload=None,
            status="running",
            step_index=idx,
        )
        db.session.add(run)
        db.session.commit()

        input_text = _build_input_for_role(role, report, completed_runs)
        run.input_payload = input_text[:64000]  # 防止超长
        db.session.commit()

        try:
            client, _provider, _extra = _build_client_for_role(role, provider)
            # head_trader 强制 JSON 输出
            response_format_json = role.role_group == "trader"
            result = client.chat(
                role.system_prompt,
                input_text,
                temperature=role.temperature,
                max_tokens=role.max_tokens,
                use_thinking=role.use_thinking,
                response_format_json=response_format_json,
            )
            parsed, cleaned = _safe_parse_json(result.text)
            if parsed is None:
                # 解析失败时,把原文以 JSON 字符串存,避免下游全挂
                payload_text = json.dumps(
                    {"_parse_error": True, "raw_text": (result.text or "")[:8000]},
                    ensure_ascii=False,
                )
                logger.warning(
                    "role %s JSON 解析失败,已保存原文。raw[:200]=%s",
                    role.name,
                    (result.text or "")[:200],
                )
            else:
                payload_text = json.dumps(parsed, ensure_ascii=False)

            run.output_payload = payload_text
            run.model_used = result.model or provider.default_model
            run.duration_ms = result.duration_ms
            run.status = "succeeded"
            run.error_message = None
            db.session.commit()

            completed_runs.append(run)

            # head_trader 输出作为 Report.payload
            if role.role_group == "trader" and parsed is not None:
                report.payload = parsed
                report.model_used = run.model_used
                report.prompt_used = role.system_prompt[:60000]
                db.session.commit()
        except Exception as exc:  # noqa: BLE001
            logger.exception("role %s 执行失败", role.name)
            run.status = "failed"
            run.error_message = (str(exc) or exc.__class__.__name__)[:2000]
            db.session.commit()
            # 任何角色失败,整份报告失败
            raise

    if report.payload is None:
        raise RuntimeError("所有角色跑完但 head_trader 未产出 payload。")
