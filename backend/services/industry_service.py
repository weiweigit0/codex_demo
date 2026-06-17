from __future__ import annotations

from statistics import mean
from typing import List

from backend.services.analysis_engine import analyze_periods


DEFAULT_PEERS = {
    "科技": ["AAPL", "MSFT", "GOOGL", "META", "NVDA"],
    "汽车": ["TSLA", "F", "GM"],
    "金融": ["JPM", "BAC", "GS", "MS"],
    "白酒": ["600519", "000858"],
}


class IndustryService:
    def __init__(self, company_service, report_service):
        self.company_service = company_service
        self.report_service = report_service

    def compare(self, ticker: str, market: str = "US", period: str = None, peer_tickers: List[str] = None) -> dict:
        company = self.company_service.resolve(ticker, market)
        industry = company.get("industry") or "待识别行业"
        tickers = peer_tickers or DEFAULT_PEERS.get(industry, [])
        if ticker.upper() not in [item.upper() for item in tickers]:
            tickers = [ticker] + tickers

        rows = []
        for peer_ticker in tickers[:6]:
            try:
                peer_company = self.company_service.resolve(peer_ticker, market)
                dataset = self.report_service.fetch_financial_dataset(peer_company)
                options = self.report_service.list_options(peer_company)
                selected_period = period or (options.get("annual") or [None])[0]
                if not selected_period:
                    continue
                result = analyze_periods(peer_company, dataset, [selected_period], "annual")
                metrics = result["metrics"]
                rows.append(
                    {
                        "ticker": peer_company["ticker"],
                        "name": peer_company["name"],
                        "industry": peer_company.get("industry"),
                        "period": selected_period,
                        "revenue": metrics.get("revenue", {}).get("display", "待补充"),
                        "revenue_yoy": metrics.get("revenue", {}).get("yoy"),
                        "net_profit": metrics.get("net_profit", {}).get("display", "待补充"),
                        "net_profit_yoy": metrics.get("net_profit", {}).get("yoy"),
                        "gross_margin": metrics.get("gross_margin", {}).get("value"),
                        "net_margin": metrics.get("net_margin", {}).get("value"),
                        "roe": metrics.get("roe", {}).get("value"),
                        "debt_ratio": metrics.get("debt_ratio", {}).get("value"),
                        "cashflow": metrics.get("operating_cashflow", {}).get("display", "待补充"),
                    }
                )
            except Exception:
                continue

        return {
            "company": company,
            "industry": industry,
            "rows": rows,
            "insight": self._build_insight(company, rows),
        }

    def _build_insight(self, company: dict, rows: List[dict]) -> str:
        if not rows:
            return "暂未形成可比公司样本，需要补充同行数据。"
        target = next((row for row in rows if row["ticker"].upper() == company["ticker"].upper()), None)
        if not target:
            return "已形成同行样本，但当前公司缺少可比指标。"
        growth_values = [row["revenue_yoy"] for row in rows if row.get("revenue_yoy") is not None]
        margin_values = [row["gross_margin"] for row in rows if row.get("gross_margin") is not None]
        parts = []
        if growth_values and target.get("revenue_yoy") is not None:
            parts.append(f"收入增速{'高于' if target['revenue_yoy'] >= mean(growth_values) else '低于'}样本均值")
        if margin_values and target.get("gross_margin") is not None:
            parts.append(f"毛利率{'高于' if target['gross_margin'] >= mean(margin_values) else '低于'}样本均值")
        return "，".join(parts) + "。" if parts else "关键同行指标不足，暂无法判断行业位置。"
