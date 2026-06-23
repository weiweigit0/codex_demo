from __future__ import annotations

from backend.data_platform.service import DataService


class CompanyService:
    """Compatibility facade for company APIs backed by the data platform."""

    def __init__(self, data_service: DataService):
        self.data_service = data_service

    def search(self, query: str, market: str = "ALL") -> list:
        return self.data_service.search_companies(query, market)

    def resolve(self, ticker_or_name: str, market: str = "US") -> dict:
        return self.data_service.resolve_company(ticker_or_name, market)

    def top(self, market: str = "ALL") -> list:
        return self.data_service.top_companies(market)


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
