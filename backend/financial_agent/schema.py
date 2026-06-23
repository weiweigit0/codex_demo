from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field


class FinancialAgentRequest(BaseModel):
    ticker: str = Field(min_length=1)
    market: str = "US"
    periods: List[str] = []
    period_type: str = "annual"
    include_peer_context: bool = False


class Observation(BaseModel):
    category: str
    claim: str
    period: str = ""
    evidence_block_ids: List[str] = []


class RiskFact(BaseModel):
    risk_category: str
    risk_name: str
    description: str
    trend: str = "unknown"
    mitigation_disclosed: List[str] = []
    evidence_block_ids: List[str] = []


class RiskAssessment(BaseModel):
    risk_category: str
    attention_level: str = "unknown"
    assessment_reason: str = ""
    positive_signals: List[str] = []
    negative_signals: List[str] = []
    uncertainties: List[str] = []
    evidence_fact_ids: List[str] = []
