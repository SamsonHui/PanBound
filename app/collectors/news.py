"""第一财经快讯 + 华尔街见闻 + IT之家 资讯。"""

from __future__ import annotations

import logging
import re
from html import unescape

from .base import BaseCollector, NewsItem, SourceResult

logger = logging.getLogger(__name__)


class YicaiFlashCollector(BaseCollector):
    """第一财经 /api/ajax/getlatest — 返回 NewsList JSON。"""

    name = "yicai_flash"
    URL = "https://www.yicai.com/api/ajax/getlatest"
    TIMEOUT = 8

    def fetch(self) -> SourceResult:
        return self.safe(self._do_fetch)

    def _do_fetch(self):
        r = self.get(self.URL, headers={"Referer": "https://www.yicai.com/"})
        if r.status_code != 200:
            raise RuntimeError(f"yicai http {r.status_code}")
        data = r.json()
        items: list[NewsItem] = []
        for d in data[:30]:
            title = (d.get("NewsTitle") or "").strip()
            if not title:
                continue
            url = d.get("url") or ""
            if url and not url.startswith("http"):
                url = "https://www.yicai.com" + url
            items.append(
                NewsItem(
                    title=title,
                    url=url,
                    summary=(d.get("NewsNotes") or "").strip(),
                    source="第一财经",
                    published_at=d.get("pubDate") or d.get("CreateDate") or "",
                    tags=[d.get("ChannelName", "")] if d.get("ChannelName") else [],
                )
            )
        return items


class WallstreetCNCollector(BaseCollector):
    """华尔街见闻 快讯/资讯 (apiv1 content/articles)。"""

    name = "wallstreetcn"
    URL = "https://api-one.wallstcn.com/apiv1/content/articles?channel=global-channel&limit=15"
    TIMEOUT = 8

    def fetch(self) -> SourceResult:
        return self.safe(self._do_fetch)

    def _do_fetch(self):
        r = self.get(self.URL, headers={"Referer": "https://wallstreetcn.com/"})
        if r.status_code != 200:
            raise RuntimeError(f"wscn http {r.status_code}")
        data = r.json()
        if data.get("code") != 20000:
            raise RuntimeError(f"wscn code={data.get('code')}")
        items: list[NewsItem] = []
        seen_ids: set[int] = set()
        for d in (data.get("data") or {}).get("items") or []:
            did = d.get("id")
            if did in seen_ids:
                continue
            seen_ids.add(did)
            title = (d.get("title") or "").strip()
            if not title:
                title = (d.get("content_short") or "").strip()[:120]
            content = d.get("content_short") or ""
            uri = d.get("uri") or ""
            url = uri if uri.startswith("http") else f"https://wallstreetcn.com{uri}"
            items.append(
                NewsItem(
                    title=title,
                    url=url,
                    summary=content[:300],
                    source="华尔街见闻",
                    published_at=str(d.get("display_time") or ""),
                    tags=d.get("categories") or [],
                )
            )
        return items


class ITHomeCollector(BaseCollector):
    """IT之家 toplist + newslist。"""

    name = "ithome"
    URL = "https://api.ithome.com/json/newslist/news?r=0"
    TIMEOUT = 8

    def fetch(self) -> SourceResult:
        return self.safe(self._do_fetch)

    def _do_fetch(self):
        r = self.get(self.URL, headers={"Referer": "https://www.ithome.com/"})
        if r.status_code != 200:
            raise RuntimeError(f"ithome http {r.status_code}")
        data = r.json()
        items: list[NewsItem] = []
        # 头条(早报)优先
        for d in data.get("toplist") or []:
            items.append(self._parse(d, top=True))
        for d in (data.get("newslist") or [])[:25]:
            items.append(self._parse(d))
        return items

    def _parse(self, d: dict, top: bool = False) -> NewsItem:
        title = (d.get("title") or "").strip()
        url = d.get("url") or ""
        if url and not url.startswith("http"):
            url = "https://www.ithome.com" + url
        desc = re.sub(r"<[^>]+>", "", unescape(d.get("description") or ""))
        return NewsItem(
            title=title,
            url=url,
            summary=desc[:200],
            source="IT之家",
            published_at=d.get("postdate") or "",
            tags=(d.get("kwdlist") or []) if not top else ["IT早报"],
        )


class GelonghuiCollector(BaseCollector):
    """格隆汇 7×24 直播 (HTML 解析)。"""

    name = "gelonghui"
    URL = "https://www.gelonghui.com/live"
    TIMEOUT = 10

    def fetch(self) -> SourceResult:
        return self.safe(self._do_fetch)

    def _do_fetch(self):
        r = self.get(self.URL, headers={"Referer": "https://www.gelonghui.com/"})
        if r.status_code != 200:
            raise RuntimeError(f"gelonghui http {r.status_code}")
        html = r.text
        # 解析 title + 简单时间
        titles = re.findall(r'<a[^>]+class="live-title[^"]*"[^>]*>(.*?)</a>', html, flags=re.S)
        if not titles:
            titles = re.findall(r'<div class="live-content[^"]*"[^>]*>(.*?)</div>', html, flags=re.S)
        items: list[NewsItem] = []
        for raw in titles[:25]:
            text = re.sub(r"<[^>]+>", "", unescape(raw)).strip()
            text = re.sub(r"\s+", " ", text)
            if not text or len(text) < 4:
                continue
            items.append(
                NewsItem(
                    title=text[:140],
                    url="https://www.gelonghui.com/live",
                    summary="",
                    source="格隆汇",
                    published_at="",
                )
            )
        if not items:
            raise RuntimeError("gelonghui 解析为空,可能反爬升级")
        return items


class ZhitongCaijingCollector(BaseCollector):
    """智通财经 快讯 (HTML 解析, 站点本身有反爬 JS 验证)。"""

    name = "zhitongcaijing"
    URL = "https://www.zhitongcaijing.com/"
    TIMEOUT = 10

    def fetch(self) -> SourceResult:
        return self.safe(self._do_fetch)

    def _do_fetch(self):
        # 该站点有 aliyun waf cookie 校验,直 GET 会被拦。
        # 退而求其次:抓首页 news 区标题。
        r = self.get(
            "https://www.zhitongcaijing.com/content/news.html",
            headers={"Referer": "https://www.zhitongcaijing.com/"},
        )
        if r.status_code != 200:
            raise RuntimeError(f"zhitong http {r.status_code}")
        html = r.text
        # 抓 <a href="/content/..."> title </a>
        matches = re.findall(r'<a[^>]+href="(/content/[^"]+)"[^>]*>([^<]{6,140})</a>', html)
        items: list[NewsItem] = []
        seen: set[str] = set()
        for href, title in matches:
            title = re.sub(r"\s+", " ", unescape(title)).strip()
            if not title or title in seen:
                continue
            seen.add(title)
            items.append(
                NewsItem(
                    title=title,
                    url="https://www.zhitongcaijing.com" + href,
                    summary="",
                    source="智通财经",
                    published_at="",
                )
            )
            if len(items) >= 20:
                break
        if not items:
            raise RuntimeError("zhitong 解析为空 (WAF 拦截)")
        return items