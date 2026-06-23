from __future__ import annotations

from typing import Optional
import re

import requests
from urllib.parse import quote


class WikipediaClient:
    def __init__(self):
        self.search_endpoint = "https://zh.wikipedia.org/w/rest.php/v1/search/title"
        self.summary_endpoint = "https://zh.wikipedia.org/api/rest_v1/page/summary/{title}"

    def fetch_company_context(self, company: dict) -> Optional[dict]:
        query = company.get("name") or company.get("short_name") or company.get("ticker")
        if not query:
            return None
        try:
            search = requests.get(
                self.search_endpoint,
                params={"q": query, "limit": 1},
                headers={"User-Agent": "FinancialReportMining/0.4"},
                timeout=8,
            )
            search.raise_for_status()
            pages = (search.json() or {}).get("pages") or []
            if not pages:
                return None
            title = pages[0].get("title")
            if not title:
                return None
            summary = requests.get(
                self.summary_endpoint.format(title=title),
                headers={"User-Agent": "FinancialReportMining/0.4"},
                timeout=8,
            )
            summary.raise_for_status()
            payload = summary.json() or {}
            extract = payload.get("extract") or ""
            if not extract.strip():
                return None
            return {
                "source_type": "wikipedia",
                "title": payload.get("title") or title,
                "summary": extract[:1200],
                "url": (payload.get("content_urls") or {}).get("desktop", {}).get("page"),
                "allowed_usage": "仅用于补充公司英文名、总部、成立背景、行业通用描述等基础背景；不得覆盖披露文件。"
            }
        except Exception:
            return None


class EncyclopediaClient:
    """Use Wikipedia first, then Baidu Baike only when Wikipedia has no usable entry."""

    def __init__(self):
        self.wikipedia = WikipediaClient()
        self.http = requests.Session()
        self.http.trust_env = False

    def fetch_company_context(self, company: dict) -> Optional[dict]:
        context = self.wikipedia.fetch_company_context(company)
        if context:
            return context
        query = company.get("name") or company.get("short_name") or company.get("ticker")
        if not query:
            return None
        try:
            url = "https://baike.baidu.com/item/%s" % quote(query)
            response = self.http.get(url, headers={"User-Agent": "Mozilla/5.0 FinancialReportMining/0.5"}, timeout=10)
            response.raise_for_status()
            html = response.content.decode(response.encoding or "utf-8", errors="ignore")
            summary = re.search(r'<meta\s+name="description"\s+content="([^"]+)"', html, re.I)
            text = summary.group(1).strip() if summary else ""
            if not text:
                return None
            return {"source_type": "baidu_baike", "title": query, "summary": text[:1200], "url": url,
                    "allowed_usage": "仅在披露文件未披露时补充基础背景；不得覆盖披露文件。"}
        except Exception:
            return None
