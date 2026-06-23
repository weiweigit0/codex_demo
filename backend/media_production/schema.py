from __future__ import annotations

from typing import Any, List, Optional

from typing_extensions import Literal

from pydantic import BaseModel, Field


class DisplayFact(BaseModel):
    fact_id: str
    label: str
    display_value: Optional[str] = None
    period_label: Optional[str] = None
    evidence_refs: List[str] = []


class VideoBriefSegment(BaseModel):
    segment_id: str
    title: str = "本期解读"
    target_duration_seconds: int = Field(ge=8, le=60)
    narration: str = Field(min_length=1, max_length=2000)
    visual_direction: str = "数据卡片与趋势图"
    display_facts: List[DisplayFact] = []
    evidence_refs: List[str] = []


class VideoBriefSource(BaseModel):
    summary_id: str
    script_id: str
    script_version: str
    company_display_name: str
    period_display_name: str


class VideoBriefRules(BaseModel):
    language: Literal["zh-CN"] = "zh-CN"
    no_new_facts: bool = True
    no_investment_advice: bool = True


class VideoBriefEnvelope(BaseModel):
    schema_version: Literal["video_brief_v1"] = "video_brief_v1"
    brief_id: str
    issued_at: str
    expires_at: str
    nonce: str
    content_hash: str
    requester_reference: str
    source: VideoBriefSource
    segments: List[VideoBriefSegment] = Field(min_items=4, max_items=8)
    content_rules: VideoBriefRules = VideoBriefRules()
    key_id: str
    signature: str

    def unsigned_payload(self) -> dict[str, Any]:
        data = self.dict()
        data.pop("signature", None)
        return data


class ImportBriefRequest(BaseModel):
    brief: VideoBriefEnvelope


class CreateRequestPayload(BaseModel):
    output_profile: Literal["vertical_720p", "landscape_720p"] = "vertical_720p"


class ReviewPayload(BaseModel):
    action: Literal["approve", "reject", "retry"]
    note: str = Field(default="", max_length=500)


class AccessPayload(BaseModel):
    access_token: str = Field(min_length=16)
