"""信源采集器基类与公共类型。"""

from __future__ import annotations

import logging
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Any

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


@dataclass
class IndexQuote:
    code: str
    name: str
    price: float
    change_pct: float
    open: float | None = None
    high: float | None = None
    low: float | None = None
    prev_close: float | None = None
    volume: float | None = None  # 手
    turnover: float | None = None  # 元
    timestamp: str | None = None


@dataclass
class StockQuote:
    code: str
    name: str
    price: float
    change_pct: float
    change: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    volume: int | None = None
    turnover: float | None = None
    pe: float | None = None
    market_cap: float | None = None
    timestamp: str | None = None


@dataclass
class NewsItem:
    title: str
    url: str
    summary: str = ""
    source: str = ""
    published_at: str = ""
    tags: list[str] = field(default_factory=list)


@dataclass
class ThemeItem:
    code: str
    name: str
    change_pct: float
    leader_code: str | None = None
    leader_name: str | None = None


@dataclass
class SourceResult:
    """单个信源的采集结果,失败时只有 ok=False + error。"""

    source: str
    ok: bool
    data: Any = None
    error: str = ""
    latency_ms: int = 0


class BaseCollector:
    """所有采集器继承此类。"""

    name: str = "base"
    enabled: bool = True

    def __init__(self, timeout: int = 8):
        self.timeout = timeout
        self.session = self._make_session()

    def _make_session(self) -> requests.Session:
        s = requests.Session()
        s.headers.update(
            {
                "User-Agent": UA,
                "Accept": "*/*",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            }
        )
        # 不验证 SSL (东财等偶尔证书链不稳)
        s.verify = False
        # 加大连接池 + 失败重试 (push2 偶尔 RST)
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry

        retry = Retry(
            total=3,
            backoff_factor=0.4,
            status_forcelist=(500, 502, 503, 504),
            allowed_methods=frozenset(["GET", "POST"]),
            respect_retry_after_header=True,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=16)
        s.mount("https://", adapter)
        s.mount("http://", adapter)
        return s

    # ----- 子类实现 -----
    def fetch(self) -> SourceResult:
        raise NotImplementedError

    # ----- 工具 -----
    def get(self, url: str, params: dict | None = None, headers: dict | None = None, timeout: int | None = None):
        return self.session.get(
            url,
            params=params,
            headers={**(headers or {})},
            timeout=timeout or self.timeout,
            verify=False,
            allow_redirects=True,
        )

    def get_with_retry(self, url: str, params: dict | None = None, headers: dict | None = None, timeout: int | None = None, retries: int = 3):
        """对 ConnectionError/ProxyError 做手动重试 (东财 push2 偶发 RST)。"""
        import time as _t
        last = None
        for i in range(retries):
            try:
                return self.get(url, params=params, headers=headers, timeout=timeout)
            except Exception as exc:  # noqa: BLE001
                last = exc
                logger.debug("[%s] retry %d: %s", self.name, i + 1, exc)
                _t.sleep(0.3 * (i + 1))
        raise last  # type: ignore[misc]

    def safe(self, fn) -> SourceResult:
        """统一封装:跑 fetch() 抓异常,记录耗时,返回 SourceResult。"""
        t0 = time.time()
        try:
            data = fn()
            return SourceResult(
                source=self.name,
                ok=True,
                data=data,
                latency_ms=int((time.time() - t0) * 1000),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[%s] 采集失败: %s", self.name, exc)
            return SourceResult(
                source=self.name,
                ok=False,
                error=str(exc)[:300],
                latency_ms=int((time.time() - t0) * 1000),
            )


def fmt_pct(v: float | None) -> str:
    if v is None or v == "" or v == "-":
        return "—"
    try:
        return f"{float(v):+.2f}%"
    except (TypeError, ValueError):
        return str(v)


def fmt_price(v: float | None) -> str:
    if v is None or v == "" or v == "-":
        return "—"
    try:
        return f"{float(v):.2f}"
    except (TypeError, ValueError):
        return str(v)


def safe_float(v: Any) -> float | None:
    if v is None or v == "" or v == "-":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def split_tencent_line(text: str) -> list[str] | None:
    """解析腾讯 qt.gtimg.cn 返回的 var sh000001="..."; 一行。"""
    if "=" not in text or '"' not in text:
        return None
    body = text.split('"', 2)
    if len(body) < 2:
        return None
    inner = body[1]
    return inner.split("~")