"""东方财富 push2delay.eastmoney.com 行情数据。"""

from __future__ import annotations

import logging

from .base import BaseCollector, SourceResult, StockQuote, ThemeItem, safe_float

logger = logging.getLogger(__name__)

# 东财 clist 字段约定: f12=code f14=name f2=now f3=change_pct f5=volume f6=turnover f9=pe f20=market_cap
# f1=market_id f8=turnover_yi f10=pe_short f15=high f16=low f17=open f18=prev_close


def _parse_diff(diff: list[dict]) -> list[dict]:
    out = []
    for d in diff:
        if not isinstance(d, dict):
            continue
        if not d.get("f12"):
            continue
        out.append(d)
    return out


class EastMoneyIndicesCollector(BaseCollector):
    """A 股主要指数。"""

    name = "em_indices"

    URL = (
        "https://push2delay.eastmoney.com/api/qt/clist/get"
        "?pn=1&pz=20&po=1&np=1&fltt=2&invt=2"
        "&fs=m:1+s:2,m:0+t:6"
        "&fields=f1,f2,f3,f4,f5,f6,f8,f9,f12,f13,f14,f15,f16,f17,f18,f20"
    )

    def fetch(self) -> SourceResult:
        return self.safe(self._do_fetch)

    def _do_fetch(self):
        r = self.get_with_retry(self.URL, headers={"Referer": "https://quote.eastmoney.com/"}, retries=3)
        if r.status_code != 200:
            raise RuntimeError(f"em http {r.status_code}")
        data = r.json()
        diff = (data.get("data") or {}).get("diff") or []
        out: list[dict] = []
        for d in diff:
            out.append(
                {
                    "code": d.get("f12"),
                    "name": d.get("f14"),
                    "now": safe_float(d.get("f2")),
                    "change_pct": safe_float(d.get("f3")),
                    "open": safe_float(d.get("f17")),
                    "high": safe_float(d.get("f15")),
                    "low": safe_float(d.get("f16")),
                    "prev_close": safe_float(d.get("f18")),
                    "volume": safe_float(d.get("f5")),
                    "turnover": safe_float(d.get("f6")),
                    "pe": safe_float(d.get("f9")),
                    "market_cap": safe_float(d.get("f20")),
                }
            )
        return out


class EastMoneyLimitUpCollector(BaseCollector):
    """涨停股池(全市场)。"""

    name = "em_limit_up"

    URL = (
        "https://push2delay.eastmoney.com/api/qt/clist/get"
        "?pn=1&pz=80&po=1&np=1&fltt=2&invt=2"
        "&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
        "&fields=f1,f2,f3,f5,f6,f12,f14"
    )

    def fetch(self) -> SourceResult:
        return self.safe(self._do_fetch)

    def _do_fetch(self):
        r = self.get_with_retry(self.URL, headers={"Referer": "https://quote.eastmoney.com/"}, retries=3)
        if r.status_code != 200:
            raise RuntimeError(f"em http {r.status_code}")
        data = r.json()
        diff = (data.get("data") or {}).get("diff") or []
        out: list[StockQuote] = []
        for d in diff:
            chg = safe_float(d.get("f3")) or 0.0
            # 取涨幅 ≥ 7% (涨停或大阳线)
            if chg < 7.0:
                continue
            out.append(
                StockQuote(
                    code=d.get("f12") or "",
                    name=d.get("f14") or "",
                    price=safe_float(d.get("f2")) or 0.0,
                    change_pct=chg,
                    volume=safe_float(d.get("f5")),
                    turnover=safe_float(d.get("f6")),
                )
            )
        # 按涨幅倒序
        out.sort(key=lambda x: x.change_pct, reverse=True)
        return out


class EastMoneyThemesCollector(BaseCollector):
    """概念板块涨幅榜。"""

    name = "em_themes"

    URL = (
        "https://push2delay.eastmoney.com/api/qt/clist/get"
        "?pn=1&pz=30&po=1&np=1&fltt=2&invt=2"
        "&fs=m:90+t:3"
        "&fields=f1,f2,f3,f12,f14"
    )

    def fetch(self) -> SourceResult:
        return self.safe(self._do_fetch)

    def _do_fetch(self):
        r = self.get_with_retry(self.URL, headers={"Referer": "https://quote.eastmoney.com/"}, retries=3)
        if r.status_code != 200:
            raise RuntimeError(f"em http {r.status_code}")
        data = r.json()
        diff = (data.get("data") or {}).get("diff") or []
        out: list[ThemeItem] = []
        for d in diff:
            out.append(
                ThemeItem(
                    code=d.get("f12") or "",
                    name=d.get("f14") or "",
                    change_pct=safe_float(d.get("f3")) or 0.0,
                )
            )
        out.sort(key=lambda x: x.change_pct, reverse=True)
        return out