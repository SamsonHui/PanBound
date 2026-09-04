"""腾讯财经 qt.gtimg.cn 行情。"""

from __future__ import annotations

import logging

from .base import BaseCollector, IndexQuote, SourceResult, split_tencent_line, safe_float

logger = logging.getLogger(__name__)

# 字段顺序参考腾讯 v_sh000001= "1~name~code~now~open~..."
# 0:未知 1:name 2:code 3:now 4:昨收 5:今开 6:成交量(手) 30:timestamp
# 31:涨跌点 32:涨跌% 33:今日最高 34:今日最低 42:成交额(亿) 48:PE 49:总市值
_TENCENT_INDEX_FIELDS = {
    "name": 1,
    "code": 2,
    "now": 3,
    "prev_close": 4,
    "open": 5,
    "volume": 6,
    "timestamp": 30,
    "change": 31,
    "change_pct": 32,
    "high": 33,
    "low": 34,
    "turnover_yi": 42,
    "pe": 48,
}

# A 股主要指数代码 (腾讯)
A_INDICES = {
    "sh000001": "上证指数",
    "sz399001": "深证成指",
    "sz399006": "创业板指",
    "sh000300": "沪深300",
    "sh000688": "科创50",
    "sz399905": "中证500",
    "sh000016": "上证50",
}

# 美股主要指数
US_INDICES = {
    "usDJI": "道琼斯",
    "usIXIC": "纳斯达克",
    "usSPX": "标普500",
    "usNDX": "纳斯达克100",
}


class TencentQuoteCollector(BaseCollector):
    """通过腾讯 qt.gtimg.cn 拉指数/美股/个股行情。"""

    name = "tencent_quote"

    def __init__(self, symbols: list[str] | None = None, timeout: int = 8):
        super().__init__(timeout=timeout)
        self.symbols = symbols or (list(A_INDICES.keys()) + list(US_INDICES.keys()))

    def fetch(self) -> SourceResult:
        return self.safe(self._do_fetch)

    def _do_fetch(self):
        joined = ",".join(self.symbols)
        url = f"https://qt.gtimg.cn/q={joined}"
        r = self.get(url, headers={"Referer": "https://finance.qq.com/"})
        if r.status_code != 200:
            raise RuntimeError(f"tencent http {r.status_code}")
        text = r.content.decode("gbk", errors="replace")
        out: list[IndexQuote] = []
        for line in text.strip().splitlines():
            parts = split_tencent_line(line)
            if not parts or len(parts) < 35:
                continue
            try:
                quote = self._parse(parts)
                if quote:
                    out.append(quote)
            except Exception as exc:  # noqa: BLE001
                logger.debug("parse line failed: %s", exc)
        return out

    def _parse(self, parts: list[str]) -> IndexQuote | None:
        if len(parts) < 50:
            return None
        code = parts[_TENCENT_INDEX_FIELDS["code"]]
        name = parts[_TENCENT_INDEX_FIELDS["name"]]
        if not code or not name:
            return None
        return IndexQuote(
            code=code,
            name=name,
            price=safe_float(parts[_TENCENT_INDEX_FIELDS["now"]]) or 0.0,
            change_pct=safe_float(parts[_TENCENT_INDEX_FIELDS["change_pct"]]) or 0.0,
            open=safe_float(parts[_TENCENT_INDEX_FIELDS["open"]]),
            high=safe_float(parts[_TENCENT_INDEX_FIELDS["high"]]),
            low=safe_float(parts[_TENCENT_INDEX_FIELDS["low"]]),
            prev_close=safe_float(parts[_TENCENT_INDEX_FIELDS["prev_close"]]),
            volume=safe_float(parts[_TENCENT_INDEX_FIELDS["volume"]]),
            turnover=safe_float(parts[_TENCENT_INDEX_FIELDS["turnover_yi"]]) * 1e8
            if safe_float(parts[_TENCENT_INDEX_FIELDS["turnover_yi"]]) is not None
            else None,
            timestamp=parts[_TENCENT_INDEX_FIELDS["timestamp"]],
        )


class TencentIndicesCollector(TencentQuoteCollector):
    """只取 A 股指数。"""

    name = "tencent_a_indices"

    def __init__(self, timeout: int = 8):
        super().__init__(symbols=list(A_INDICES.keys()), timeout=timeout)


class TencentUSIndicesCollector(TencentQuoteCollector):
    """只取美股指数。"""

    name = "tencent_us_indices"

    def __init__(self, timeout: int = 8):
        super().__init__(symbols=list(US_INDICES.keys()), timeout=timeout)