"""格隆汇 + 凤凰财经 + 金融界 + 汇通 HTML 解析。"""

from __future__ import annotations

import logging
import re
from html import unescape

from .base import BaseCollector, NewsItem, SourceResult

logger = logging.getLogger(__name__)


_HEAD_HINT_RE = re.compile(
    r"国内|国际|监管|央行|工信部|发改委|证监会|上交所|深交所|港股|A股|美股|"
    r"板块|龙头|涨停|跌停|连板|加速|分歧|修复|情绪|题材|主线|切换|回升|杀跌|"
    r"开盘|收盘|午盘|竞价|跳水|拉升|封板|炸板|半导体|芯片|算力|AI|机器人|"
    r"新能源|光伏|锂电|储能|医药|白酒|消费|金融|地产|军工|低空|固态电池|数据要素|"
    r"中字头|红利|煤炭|钢铁|化工|猪肉|创新药|医美|算力|消费电子|"
    r"人民币|汇率|国债|期货|黄金|原油|天然气|加息|降息|非农|CPI|PMI|财报|"
    r"会议|政策|规划|定调|部署|印发|批复|试点|纳入|剔除|下调|上调",
    re.IGNORECASE,
)


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", unescape(text or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text


class GelonghuiLiveCollector(BaseCollector):
    """格隆汇 公告/资讯列表:解析 /p/{id} 文章链接的标题。"""

    name = "gelonghui"
    URL = "https://www.gelonghui.com/news?type=40"
    TIMEOUT = 10

    def fetch(self) -> SourceResult:
        return self.safe(self._do_fetch)

    def _do_fetch(self):
        r = self.get(self.URL, headers={"Referer": "https://www.gelonghui.com/"})
        if r.status_code != 200:
            raise RuntimeError(f"gelonghui http {r.status_code}")
        html = r.text
        items: list[NewsItem] = []
        for m in re.finditer(r'<a[^>]+href="(/p/\d+)"[^>]*>([^<]{6,160})</a>', html):
            href, raw = m.group(1), m.group(2)
            title = _clean(raw)
            if len(title) < 6:
                continue
            if not _HEAD_HINT_RE.search(title):
                continue
            url = "https://www.gelonghui.com" + href
            if any(it.title == title for it in items):
                continue
            items.append(
                NewsItem(title=title[:140], url=url, summary="", source="格隆汇", published_at="")
            )
            if len(items) >= 20:
                break
        if not items:
            raise RuntimeError("gelonghui 解析为空")
        return items


class IfengFinanceCollector(BaseCollector):
    """凤凰财经首页标题。"""

    name = "ifeng"
    URL = "https://finance.ifeng.com/"
    TIMEOUT = 10

    def fetch(self) -> SourceResult:
        return self.safe(self._do_fetch)

    def _do_fetch(self):
        r = self.get(self.URL, headers={"Referer": "https://www.ifeng.com/"})
        if r.status_code != 200:
            raise RuntimeError(f"ifeng http {r.status_code}")
        html = r.text
        items: list[NewsItem] = []
        for m in re.finditer(
            r'<a[^>]+href="(https?://finance\.ifeng\.com/[^"]+|/c/[^"]+)"[^>]*>([^<]{6,140})</a>',
            html,
        ):
            href, raw = m.group(1), m.group(2)
            title = _clean(raw)
            if not _HEAD_HINT_RE.search(title):
                continue
            if title in (it.title for it in items):
                continue
            url = href if href.startswith("http") else "https://finance.ifeng.com" + href
            items.append(
                NewsItem(title=title[:140], url=url, summary="", source="凤凰财经", published_at="")
            )
            if len(items) >= 20:
                break
        if not items:
            raise RuntimeError("ifeng 解析为空")
        return items


class JRJFlashCollector(BaseCollector):
    """金融界 7x24 电报。"""

    name = "jrj_flash"
    URL = "https://24h.jrj.com.cn/newsFlash"
    TIMEOUT = 10

    def fetch(self) -> SourceResult:
        return self.safe(self._do_fetch)

    def _do_fetch(self):
        r = self.get(self.URL, headers={"Referer": "https://www.jrj.com.cn/"})
        if r.status_code != 200:
            raise RuntimeError(f"jrj http {r.status_code}")
        html = r.text
        items: list[NewsItem] = []
        # 抓新闻条目 <a>...</a>
        for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>([^<]{8,200})</a>', html):
            href, raw = m.group(1), m.group(2)
            title = _clean(raw)
            if not _HEAD_HINT_RE.search(title):
                continue
            if title in (it.title for it in items):
                continue
            url = href if href.startswith("http") else "https:" + href if href.startswith("//") else "https://24h.jrj.com.cn" + href
            items.append(
                NewsItem(title=title[:140], url=url, summary="", source="金融界", published_at="")
            )
            if len(items) >= 20:
                break
        if not items:
            raise RuntimeError("jrj 解析为空")
        return items


class FX678Collector(BaseCollector):
    """汇通网 fx678 头条。"""

    name = "fx678"
    URL = "https://www.fx678.com/"
    TIMEOUT = 10

    def fetch(self) -> SourceResult:
        return self.safe(self._do_fetch)

    def _do_fetch(self):
        r = self.get(self.URL, headers={"Referer": "https://www.fx678.com/"})
        if r.status_code != 200:
            raise RuntimeError(f"fx678 http {r.status_code}")
        html = r.text
        items: list[NewsItem] = []
        for m in re.finditer(
            r'<a[^>]+href="(https?://news\.fx678\.com/\d+\.shtml|//news\.fx678\.com/[^"]+)"[^>]*>([^<]{6,140})</a>',
            html,
        ):
            href, raw = m.group(1), m.group(2)
            title = _clean(raw)
            if not _HEAD_HINT_RE.search(title):
                continue
            if title in (it.title for it in items):
                continue
            if href.startswith("//"):
                href = "https:" + href
            items.append(
                NewsItem(title=title[:140], url=href, summary="", source="汇通fx678", published_at="")
            )
            if len(items) >= 15:
                break
        if not items:
            raise RuntimeError("fx678 解析为空")
        return items