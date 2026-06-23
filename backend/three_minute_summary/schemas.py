from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class CreateSummaryRequest(BaseModel):
    ticker: str = Field(min_length=1)
    market: str = "US"
    period_type: str = "annual"
    period: Optional[str] = None
    allow_web_enrichment: bool = False


class SummaryQuestionRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
