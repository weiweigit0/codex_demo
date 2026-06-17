from typing import Dict, List, Optional

from pydantic import BaseModel


class Company(BaseModel):
    id: str
    name: str
    ticker: str
    market: str
    exchange: Optional[str] = None
    industry: Optional[str] = None
    short_name: Optional[str] = None
    cik: Optional[str] = None
    source: Optional[str] = None


class ReportMeta(BaseModel):
    id: str
    company_id: str
    report_type: str
    period: str
    publish_date: Optional[str] = None
    source_url: Optional[str] = None
    file_path: Optional[str] = None
    parse_status: str = "pending"


class Citation(BaseModel):
    title: str
    content: str
    url: Optional[str] = None
    page: Optional[int] = None
    score: Optional[float] = None


class RiskItem(BaseModel):
    name: str
    level: str
    reason: str
    evidence: Optional[str] = None


class AnalyzeRequest(BaseModel):
    ticker: str
    market: str = "US"
    periods: Optional[List[str]] = None
    period_type: str = "annual"


class QaRequest(BaseModel):
    question: str
    analysis: Optional[dict] = None
    company_id: Optional[str] = None
    report_id: Optional[str] = None


class WatchlistRequest(BaseModel):
    company: Company


class AlertRequest(BaseModel):
    company_id: str
    metric: str
    condition: str
    threshold: Optional[float] = None


class IndustryCompareRequest(BaseModel):
    ticker: str
    market: str = "US"
    period: Optional[str] = None
    peer_tickers: Optional[List[str]] = None


class RegisterRequest(BaseModel):
    username: str
    password: str
    phone: str


class LoginRequest(BaseModel):
    username: str
    password: str


class AnalysisResult(BaseModel):
    company: dict
    latest_period: str
    period_type: str
    selected_periods: List[str]
    metrics: Dict[str, dict]
    risks: List[dict]
    score: int
    stance: str
    summary: str
    business_model: str
    highlights: List[str]
    watch_metrics: List[str]
    comparison: dict
    sources: List[dict]
    rag_chunks: List[dict]
    disclaimer: str
