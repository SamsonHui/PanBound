"""聚合所有 collector,生成 raw_context 文本。

设计目标:
- 任何 collector 失败都不会阻塞主流程。
- 全部并行触发(线程池),整体耗时 < 最慢源。
- 失败时 log + 写进 context 的 [信源状态] 区块,方便用户知晓。
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Iterable

from .base import (
    BaseCollector,
    IndexQuote,
    NewsItem,
    SourceResult,
    StockQuote,
    ThemeItem,
    fmt_pct,
    fmt_price,
)
from .eastmoney import (
    EastMoneyIndicesCollector,
    EastMoneyLimitUpCollector,
    EastMoneyThemesCollector,
)
from .news import (
    ITHomeCollector,
    WallstreetCNCollector,
    YicaiFlashCollector,
)
from .news2 import (
    FX678Collector,
    GelonghuiLiveCollector,
    IfengFinanceCollector,
    JRJFlashCollector,
)
from .tencent import (
    TencentIndicesCollector,
    TencentQuoteCollector,
    TencentUSIndicesCollector,
)

logger = logging.getLogger(__name__)


def default_collectors() -> list[BaseCollector]:
    return [
        TencentIndicesCollector(),
        TencentUSIndicesCollector(),
        EastMoneyIndicesCollector(),
        EastMoneyLimitUpCollector(),
        EastMoneyThemesCollector(),
        YicaiFlashCollector(),
        WallstreetCNCollector(),
        GelonghuiLiveCollector(),
        IfengFinanceCollector(),
        JRJFlashCollector(),
        FX678Collector(),
        ITHomeCollector(),
    ]


def run_all(collectors: Iterable[BaseCollector] | None = None) -> list[SourceResult]:
    collectors = list(collectors) if collectors is not None else default_collectors()
    results: list[SourceResult] = []
    with ThreadPoolExecutor(max_workers=min(8, len(collectors))) as ex:
        future_to_c = {ex.submit(c.fetch): c for c in collectors}
        for fut in as_completed(future_to_c, timeout=20):
            try:
                results.append(fut.result(timeout=15))
            except Exception as exc:  # noqa: BLE001
                c = future_to_c[fut]
                results.append(SourceResult(source=c.name, ok=False, error=str(exc)[:200]))
    return results


# ---------------------------------------------------------------------------
# 文本合成
# ---------------------------------------------------------------------------


def _by_source(results: list[SourceResult], name: str) -> SourceResult | None:
    for r in results:
        if r.source == name:
            return r
    return None


def _index_lines(items: list[IndexQuote] | None) -> str:
    if not items:
        return "(无数据)"
    out = []
    for it in items:
        arrow = "↑" if it.change_pct > 0 else ("↓" if it.change_pct < 0 else "—")
        out.append(
            f"  {it.name}({it.code}) {fmt_price(it.price)} {arrow} {fmt_pct(it.change_pct)}"
        )
    return "\n".join(out)


def _theme_lines(items: list[ThemeItem] | None, limit: int = 15) -> str:
    if not items:
        return "(无数据)"
    out = []
    for it in items[:limit]:
        out.append(f"  {it.name} {fmt_pct(it.change_pct)}")
    return "\n".join(out)


def _limit_up_lines(items: list[StockQuote] | None, limit: int = 20) -> str:
    if not items:
        return "(无涨停股或未抓到)"
    out = []
    for it in items[:limit]:
        out.append(f"  {it.name}({it.code}) {fmt_price(it.price)} {fmt_pct(it.change_pct)}")
    return "\n".join(out)


def _news_lines(items: list[NewsItem] | None, limit: int = 15) -> str:
    if not items:
        return "(无数据)"
    out = []
    for it in items[:limit]:
        ts = f" [{it.published_at}]" if it.published_at else ""
        out.append(f"  · [{it.source}]{ts} {it.title}")
    return "\n".join(out)


def compose_context(results: list[SourceResult], *, trade_date: str | None = None, max_chars: int = 14000) -> str:
    """把所有信源结果拼成 raw_context 文本(限长)。"""
    chunks: list[str] = []

    # 标题
    if trade_date:
        chunks.append(f"# 交易日 {trade_date}\n# 自动采集的盘面快照(多源合并)\n")
    else:
        chunks.append("# 自动采集的盘面快照(多源合并)\n")

    a_idx = _by_source(results, "tencent_a_indices")
    us_idx = _by_source(results, "tencent_us_indices")
    em_idx = _by_source(results, "em_indices")
    limit_up = _by_source(results, "em_limit_up")
    themes = _by_source(results, "em_themes")

    chunks.append("## 1. A 股主要指数 (腾讯)\n")
    if a_idx and a_idx.ok and a_idx.data:
        chunks.append(_index_lines(a_idx.data))
    else:
        chunks.append("(腾讯 A 股指数失败)")
    if em_idx and em_idx.ok and em_idx.data:
        chunks.append("\n## 1b. A 股主要指数 (东方财富 补充)\n")
        # 只展示 change_pct 与腾讯不同的源,避免重复
        seen_codes = {it.code for it in (a_idx.data or [])} if a_idx and a_idx.ok else set()
        extra = [d for d in em_idx.data if d.get("code") not in seen_codes]
        chunks.append(_index_lines(_to_index_quotes(extra)) if extra else "(与腾讯一致,省略)")

    chunks.append("\n\n## 2. 美股隔夜指数 (腾讯)\n")
    if us_idx and us_idx.ok and us_idx.data:
        chunks.append(_index_lines(us_idx.data))
    else:
        chunks.append("(未抓到)")

    chunks.append("\n\n## 3. 涨停股池 (东方财富)\n")
    if limit_up and limit_up.ok and limit_up.data:
        chunks.append(_limit_up_lines(limit_up.data))
    else:
        chunks.append("(未抓到)")

    chunks.append("\n\n## 4. 概念板块涨幅榜 (东方财富)\n")
    if themes and themes.ok and themes.data:
        chunks.append(_theme_lines(themes.data))
    else:
        chunks.append("(未抓到)")

    # 资讯
    for src_name, label in [
        ("yicai_flash", "5. 第一财经快讯"),
        ("wallstreetcn", "6. 华尔街见闻"),
        ("gelonghui", "7. 格隆汇 7x24"),
        ("ifeng", "8. 凤凰财经"),
        ("jrj_flash", "9. 金融界 7x24"),
        ("fx678", "10. 汇通fx678"),
        ("ithome", "11. IT之家 科技"),
    ]:
        r = _by_source(results, src_name)
        chunks.append(f"\n\n## {label}\n")
        if r and r.ok and r.data:
            chunks.append(_news_lines(r.data))
        else:
            chunks.append(f"(未抓到,err={r.error if r else 'n/a'})")

    # 信源状态
    chunks.append("\n\n## [信源状态]\n")
    for r in sorted(results, key=lambda x: x.source):
        chunks.append(f"  - {r.source}: {'OK' if r.ok else 'FAIL'} {r.latency_ms}ms {r.error[:60] if r.error else ''}")

    text = "\n".join(chunks)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n...(截断)..."
    return text


def _to_index_quotes(items: list[dict]) -> list[IndexQuote]:
    out = []
    for d in items:
        out.append(
            IndexQuote(
                code=d.get("code") or "",
                name=d.get("name") or "",
                price=d.get("now") or 0.0,
                change_pct=d.get("change_pct") or 0.0,
                open=d.get("open"),
                high=d.get("high"),
                low=d.get("low"),
                prev_close=d.get("prev_close"),
            )
        )
    return out


def collect_and_compose(trade_date: str | None = None) -> tuple[list[SourceResult], str]:
    """便捷入口:返回 (results, context_text)。"""
    t0 = time.time()
    results = run_all()
    text = compose_context(results, trade_date=trade_date)
    logger.info("全量采集完成 %d 源, 文本 %d 字符, 耗时 %dms", len(results), len(text), int((time.time() - t0) * 1000))
    return results, text
