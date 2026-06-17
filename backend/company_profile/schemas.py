from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class CreateProfileReportRequest(BaseModel):
    query: str
    market: str = "auto"
    document_type: str = "auto"
    year: Optional[int] = None
    report_style: str = "plain"


class ProfileQaRequest(BaseModel):
    question: str
    conversation_id: Optional[str] = None
