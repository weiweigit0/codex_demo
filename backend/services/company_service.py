from __future__ import annotations

from backend.data_sources.ashare_source import AShareSource
from backend.data_sources.sec_source import SecClient, SecClientError


class CompanyService:
    def __init__(self, sec_client: SecClient, ashare_source: AShareSource):
        self.sec_client = sec_client
        self.ashare_source = ashare_source

    def search(self, query: str, market: str = "ALL") -> list:
        results = []
        normalized = market.upper()
        if normalized in {"ALL", "US"}:
            try:
                results.extend(self.sec_client.search_companies(query))
            except SecClientError:
                pass
        if normalized in {"ALL", "CN", "A"}:
            results.extend(self.ashare_source.search_companies(query))
        return [_normalize_company(item) for item in results]

    def resolve(self, ticker_or_name: str, market: str = "US") -> dict:
        normalized = market.upper()
        if normalized in {"CN", "A"}:
            return _normalize_company(self.ashare_source.resolve_company(ticker_or_name))
        return _normalize_company(self.sec_client.resolve_company(ticker_or_name))

    def top(self, market: str = "ALL") -> list:
        normalized = market.upper()
        results = []
        if normalized in {"ALL", "US"}:
            results.extend(_local_top_us())
        if normalized in {"ALL", "CN", "A"}:
            results.extend(self.ashare_source.top_companies(limit=80))
        return [_normalize_company(item) for item in results]


def _normalize_company(item: dict) -> dict:
    market = item.get("market", "US")
    ticker = item.get("ticker", "")
    company_id = item.get("id") or f"{market}-{ticker}"
    return {
        "id": company_id,
        "cik": item.get("cik"),
        "ticker": ticker,
        "name": item.get("name", ""),
        "short_name": item.get("short_name"),
        "market": market,
        "exchange": item.get("exchange"),
        "industry": item.get("industry") or infer_industry(item.get("name", ""), ticker),
        "source": item.get("source"),
        "org_id": item.get("org_id"),
    }


def infer_industry(name: str, ticker: str) -> str:
    upper = ticker.upper()
    if upper in {"AAPL", "MSFT", "GOOGL", "GOOG", "META", "NVDA"}:
        return "科技"
    if upper in {"TSLA", "F", "GM"}:
        return "汽车"
    if upper in {"JPM", "BAC", "GS", "MS"}:
        return "金融"
    if "apple" in name.lower() or "microsoft" in name.lower():
        return "科技"
    return "待识别行业"


def _local_top_us() -> list:
    return [
        {"id": "US-AAPL", "ticker": "AAPL", "name": "Apple Inc.", "market": "US", "industry": "科技"},
        {"id": "US-MSFT", "ticker": "MSFT", "name": "Microsoft", "market": "US", "industry": "科技"},
        {"id": "US-NVDA", "ticker": "NVDA", "name": "NVIDIA", "market": "US", "industry": "科技"},
        {"id": "US-GOOGL", "ticker": "GOOGL", "name": "Alphabet", "market": "US", "industry": "科技"},
        {"id": "US-META", "ticker": "META", "name": "Meta Platforms", "market": "US", "industry": "科技"},
        {"id": "US-BIDU", "ticker": "BIDU", "name": "Baidu, Inc.", "market": "US", "industry": "互联网"},
        {"id": "US-TSLA", "ticker": "TSLA", "name": "Tesla", "market": "US", "industry": "汽车"},
        {"id": "US-AMZN", "ticker": "AMZN", "name": "Amazon", "market": "US", "industry": "互联网零售"},
        {"id": "US-JPM", "ticker": "JPM", "name": "JPMorgan Chase", "market": "US", "industry": "金融"},
    ]
