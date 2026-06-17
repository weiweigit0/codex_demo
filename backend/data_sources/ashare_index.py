from __future__ import annotations

import time
from typing import List

import requests


CNINFO_STOCK_INDEX_URL = "http://www.cninfo.com.cn/new/data/szse_stock.json"
CNINFO_INDEX_HEADERS = {
    "User-Agent": "Mozilla/5.0 FinancialReportMining/0.4",
    "Referer": "http://www.cninfo.com.cn/new/commonUrl/pageOfSearch?url=disclosure/list/search",
}

TOP_A_SHARE_CODES = {
    "000001",
    "000333",
    "000568",
    "000651",
    "000725",
    "000858",
    "002027",
    "002142",
    "002230",
    "002241",
    "002371",
    "002415",
    "002475",
    "002594",
    "002714",
    "300015",
    "300059",
    "300122",
    "300124",
    "300274",
    "300308",
    "300450",
    "300750",
    "600000",
    "600009",
    "600028",
    "600030",
    "600036",
    "600048",
    "600050",
    "600104",
    "600196",
    "600276",
    "600309",
    "600406",
    "600436",
    "600519",
    "600570",
    "600585",
    "600690",
    "600809",
    "600887",
    "600900",
    "601012",
    "601066",
    "601088",
    "601166",
    "601318",
    "601328",
    "601398",
    "601628",
    "601668",
    "601688",
    "601857",
    "601888",
    "601899",
    "601988",
    "603259",
    "603288",
    "603501",
    "603986",
    "688012",
    "688036",
    "688111",
    "688126",
    "688169",
    "688223",
    "688256",
    "688271",
    "688303",
    "688599",
    "688981",
}

FALLBACK_A_SHARE_COMPANIES = [
    ("000001", "平安银行", "payh", "gssz0000001"),
    ("000333", "美的集团", "mdjt", "gshk0000419"),
    ("000651", "格力电器", "gldq", "gssz0000651"),
    ("000858", "五粮液", "wly", "gssz0000858"),
    ("002594", "比亚迪", "byd", "gshk0001211"),
    ("300059", "东方财富", "dfcf", "9900004636"),
    ("300750", "宁德时代", "ndsd", "GD165627"),
    ("600036", "招商银行", "zsyh", "gssh0600036"),
    ("600276", "恒瑞医药", "hryy", "gssh0600276"),
    ("600309", "万华化学", "whhx", "gssh0600309"),
    ("600519", "贵州茅台", "gzmt", "gssh0600519"),
    ("601318", "中国平安", "zgpa", "9900002221"),
    ("601398", "工商银行", "gsyh", "gssh0601398"),
    ("601888", "中国中免", "zgzm", "9900023395"),
    ("688981", "中芯国际", "zxgj", "gshk0000981"),
]


class AShareIndex:
    def __init__(self, ttl_seconds: int = 3600):
        self.ttl_seconds = ttl_seconds
        self._cache: List[dict] | None = None
        self._cache_at = 0.0
        self._using_fallback = False

    def search(self, query: str, limit: int = 20) -> List[dict]:
        q = query.strip().lower()
        if not q:
            return self.top(limit=limit)
        matches = [
            item
            for item in self.load()
            if q in item["ticker"].lower()
            or q in item["name"].lower()
            or q in item.get("short_name", "").lower()
            or q in item.get("pinyin", "").lower()
        ]
        return matches[: max(1, min(limit, 100))]

    def resolve(self, ticker_or_name: str) -> dict:
        q = ticker_or_name.strip().lower()
        items = self.load()
        exact = [
            item
            for item in items
            if item["ticker"].lower() == q
            or item["name"].lower() == q
            or item.get("short_name", "").lower() == q
        ]
        if exact:
            return exact[0]
        matches = self.search(ticker_or_name, limit=1)
        if not matches:
            raise ValueError(f"暂未在 A 股公司索引中找到：{ticker_or_name}")
        return matches[0]

    def top(self, limit: int = 80) -> List[dict]:
        items = [item for item in self.load() if item["ticker"] in TOP_A_SHARE_CODES]
        return sorted(items, key=lambda item: item["ticker"])[: max(1, min(limit, 200))]

    def coverage(self) -> dict:
        items = self.load()
        return {
            "count": len(items),
            "using_fallback": self._using_fallback,
            "source": "巨潮资讯股票索引" if not self._using_fallback else "本地 A 股头部公司兜底索引",
        }

    def load(self) -> List[dict]:
        if self._cache is not None and time.time() - self._cache_at < self.ttl_seconds:
            return self._cache
        try:
            response = requests.get(CNINFO_STOCK_INDEX_URL, headers=CNINFO_INDEX_HEADERS, timeout=8)
            response.raise_for_status()
            data = response.json()
            raw_items = data.get("stockList") or []
            items = [_normalize_stock(item) for item in raw_items if item.get("category") == "A股"]
            if not items:
                raise ValueError("巨潮股票索引为空")
            self._cache = sorted(items, key=lambda item: item["ticker"])
            self._using_fallback = False
        except Exception:
            self._cache = _fallback_items()
            self._using_fallback = True
        self._cache_at = time.time()
        return self._cache


def _normalize_stock(item: dict) -> dict:
    ticker = str(item.get("code", "")).strip()
    name = str(item.get("zwjc", "")).strip()
    exchange = _exchange_for(ticker)
    return {
        "id": f"CN-{exchange}-{ticker}",
        "ticker": ticker,
        "name": name,
        "short_name": name,
        "market": "CN",
        "exchange": exchange,
        "industry": "待识别行业",
        "source": "巨潮资讯",
        "org_id": item.get("orgId"),
        "pinyin": item.get("pinyin", ""),
    }


def _fallback_items() -> List[dict]:
    return [
        _normalize_stock({"code": code, "zwjc": name, "pinyin": pinyin, "orgId": org_id, "category": "A股"})
        for code, name, pinyin, org_id in FALLBACK_A_SHARE_COMPANIES
    ]


def _exchange_for(ticker: str) -> str:
    if ticker.startswith(("600", "601", "603", "605", "688", "689")):
        return "SSE"
    if ticker.startswith(("000", "001", "002", "003", "300", "301")):
        return "SZSE"
    if ticker.startswith(("4", "8", "9")):
        return "BSE"
    return "CN"
