from __future__ import annotations

import time
from typing import List

import requests

from backend.data_sources.ashare_index import AShareIndex


SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_HEADERS = {
    "User-Agent": "FinancialReportMiningSupportCatalog/1.0 contact@example.com",
    "Accept-Encoding": "gzip, deflate",
}

TOP_US_TICKERS = {
    "AAPL",
    "MSFT",
    "NVDA",
    "GOOGL",
    "GOOG",
    "META",
    "BIDU",
    "TSLA",
    "AMZN",
    "JPM",
    "BAC",
    "BRK-B",
    "WMT",
    "LLY",
    "V",
    "MA",
    "UNH",
    "XOM",
    "COST",
    "NFLX",
    "AMD",
}

LOCAL_US_SUPPORTED = [
    ("AAPL", "Apple Inc.", "科技"),
    ("MSFT", "Microsoft Corp.", "科技"),
    ("NVDA", "NVIDIA Corp.", "科技"),
    ("GOOGL", "Alphabet Inc.", "科技"),
    ("GOOG", "Alphabet Inc.", "科技"),
    ("META", "Meta Platforms, Inc.", "科技"),
    ("BIDU", "Baidu, Inc.", "互联网"),
    ("TSLA", "Tesla, Inc.", "汽车"),
    ("AMZN", "Amazon.com, Inc.", "消费/零售"),
    ("JPM", "JPMorgan Chase & Co.", "金融"),
    ("BAC", "Bank of America Corp.", "金融"),
    ("BRK-B", "Berkshire Hathaway Inc.", "金融"),
    ("WMT", "Walmart Inc.", "消费/零售"),
    ("LLY", "Eli Lilly and Co.", "医药健康"),
    ("V", "Visa Inc.", "金融"),
    ("MA", "Mastercard Inc.", "金融"),
    ("UNH", "UnitedHealth Group Inc.", "医药健康"),
    ("XOM", "Exxon Mobil Corp.", "能源"),
    ("COST", "Costco Wholesale Corp.", "消费/零售"),
    ("NFLX", "Netflix, Inc.", "科技"),
    ("AMD", "Advanced Micro Devices, Inc.", "科技"),
]


class SupportCatalog:
    def __init__(self):
        self._sec_cache = None
        self._sec_cache_at = 0.0
        self._ashare_index = AShareIndex()

    def query(self, q: str = "", market: str = "ALL", limit: int = 200) -> dict:
        normalized_market = market.upper()
        items = []
        if normalized_market in {"ALL", "US"}:
            items.extend(self._query_us(q))
        if normalized_market in {"ALL", "CN", "A"}:
            items.extend(self._query_cn(q))

        items = sorted(items, key=lambda item: (item["market"], item["ticker"]))
        return {
            "items": items[: max(1, min(limit, 1000))],
            "total_returned": min(len(items), max(1, min(limit, 1000))),
            "total_matched": len(items),
            "coverage": self.coverage(),
        }

    def top(self) -> dict:
        us_items = [item for item in self._load_us() if item["ticker"] in TOP_US_TICKERS]
        return {
            "items": sorted(us_items + self._query_cn("", top=True), key=lambda item: (item["market"], item["ticker"])),
            "coverage": self.coverage(),
        }

    def coverage(self) -> dict:
        sec_count = len(self._load_us())
        sec_is_fallback = self._sec_cache == self._fallback_us()
        cn_coverage = self._ashare_index.coverage()
        return {
            "US": {
                "status": "支持" if not sec_is_fallback else "本地索引可用",
                "count": sec_count,
                "source": "SEC EDGAR company_tickers / companyfacts / submissions",
                "abilities": ["公司搜索", "10-K/10-Q/20-F/6-K 报告期", "结构化财务指标", "SEC filing 来源链接", "多期对比"],
                "note": "覆盖 SEC company_tickers 清单内公司；SEC 网络不可用时展示本地头部公司索引。",
            },
            "CN": {
                "status": "支持" if not cn_coverage["using_fallback"] else "本地索引可用",
                "count": cn_coverage["count"],
                "source": f"{cn_coverage['source']} + 巨潮资讯公告 PDF",
                "abilities": ["公司搜索", "巨潮公告", "PDF 解析", "结构化指标", "上传/粘贴分析"],
                "note": "覆盖巨潮股票索引中的 A 股公司；报告期可分析性取决于公告 PDF 可下载和解析完整度。",
            },
        }

    def _query_us(self, q: str) -> List[dict]:
        query = q.strip().lower()
        items = self._load_us()
        if not query:
            return [item for item in items if item["ticker"] in TOP_US_TICKERS]
        return [
            item
            for item in items
            if query in item["ticker"].lower() or query in item["name"].lower()
        ]

    def _query_cn(self, q: str, top: bool = False) -> List[dict]:
        items = self._ashare_index.top(limit=80) if top or not q.strip() else self._ashare_index.search(q, limit=300)
        return [_support_cn_item(item) for item in items]

    def _load_us(self) -> List[dict]:
        if self._sec_cache and time.time() - self._sec_cache_at < 3600:
            return self._sec_cache
        try:
            response = requests.get(SEC_TICKERS_URL, headers=SEC_HEADERS, timeout=6)
            response.raise_for_status()
            data = response.json()
            self._sec_cache = [
                {
                    "id": f"US-{item['ticker']}",
                    "ticker": item["ticker"],
                    "name": item["title"],
                    "market": "US",
                    "exchange": None,
                    "industry": _infer_industry(item["ticker"], item["title"]),
                    "source": "SEC EDGAR",
                    "abilities": ["公司搜索", "10-K/10-Q/20-F/6-K", "结构化指标", "多期对比", "来源链接"],
                    "status": "支持",
                    "note": "可分析报告期取决于公司 SEC 表单和 XBRL 披露口径。",
                }
                for item in data.values()
            ]
        except requests.RequestException:
            self._sec_cache = self._fallback_us()
        self._sec_cache_at = time.time()
        return self._sec_cache

    def _fallback_us(self) -> List[dict]:
        return [
            {
                "id": f"US-{ticker}",
                "ticker": ticker,
                "name": name,
                "market": "US",
                "exchange": None,
                "industry": industry,
                "source": "本地头部公司索引",
                "abilities": ["公司搜索", "10-K/10-Q/20-F/6-K", "结构化指标", "多期对比", "来源链接"],
                "status": "支持",
                "note": "SEC 全量清单暂不可用时的本地兜底；实际报告期以主分析页联网结果为准。",
            }
            for ticker, name, industry in LOCAL_US_SUPPORTED
        ]


def _infer_industry(ticker: str, name: str) -> str:
    upper = ticker.upper()
    if upper in {"AAPL", "MSFT", "NVDA", "GOOGL", "GOOG", "META", "AMD"}:
        return "科技"
    if upper in {"TSLA", "F", "GM"}:
        return "汽车"
    if upper in {"JPM", "BAC", "GS", "MS", "BRK-B"}:
        return "金融"
    if upper in {"WMT", "COST", "AMZN"}:
        return "消费/零售"
    if upper in {"LLY", "UNH"}:
        return "医药健康"
    lowered = name.lower()
    if "bank" in lowered or "financial" in lowered:
        return "金融"
    if "energy" in lowered or "oil" in lowered:
        return "能源"
    return "待识别行业"


def _support_cn_item(item: dict) -> dict:
    return {
        "id": item["id"],
        "ticker": item["ticker"],
        "name": item["name"],
        "market": "CN",
        "exchange": item.get("exchange"),
        "industry": item.get("industry") or "待识别行业",
        "source": item.get("source") or "巨潮资讯",
        "abilities": ["公司搜索", "巨潮公告", "PDF 解析", "结构化指标", "上传/粘贴分析"],
        "status": "支持",
        "note": "支持巨潮资讯公告 PDF 抓取和核心指标解析；解析完整度受公告版式影响。",
    }
