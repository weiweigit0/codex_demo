from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class SourceNote(BaseModel):
    source_type: str = Field("filing", description="filing, wikipedia, inferred, missing")
    evidence_refs: List[str] = []
    confidence: str = "medium"


class CompanyProfileBlock(BaseModel):
    full_name: str = ""
    short_name: str = ""
    stock_code: str = ""
    market: str = "CN_A"
    exchange: Optional[str] = None
    industry: str = "未披露"
    main_business: str = "未披露"
    controlling_shareholder: str = "未披露"
    actual_controller: str = "未披露"
    headquarters: str = ""
    evidence_refs: List[str] = []


class BusinessSegment(BaseModel):
    name: str = "主营业务"
    core_products_or_services: List[str] = []
    revenue_source_description: str = ""
    plain_explanation: str = ""
    evidence_refs: List[str] = []


class BusinessModelBlock(BaseModel):
    business_summary: str = "未披露"
    business_segments: List[BusinessSegment] = []
    evidence_refs: List[str] = []


class OwnershipBlock(BaseModel):
    controlling_shareholder: str = "未披露"
    actual_controller: str = "未披露"
    control_type: str = "unknown"
    shareholders: List[dict] = []
    ownership_tags: List[str] = []
    plain_explanation: str = "当前披露文件中未能确认控制权信息。"
    evidence_refs: List[str] = []


class KeyPerson(BaseModel):
    name: str
    role: str = "关键人物"
    background: str = ""
    importance_reason: str = ""
    tags: List[str] = []
    source_type: str = "filing"
    evidence_refs: List[str] = []


class IndustryChainBlock(BaseModel):
    upstream: List[str] = []
    company_position: str = "未披露"
    downstream: List[str] = []
    end_users: List[str] = []
    major_customers: List[str] = []
    major_suppliers: List[str] = []
    bargaining_power_note: str = "不进行竞争力或议价能力评级。"
    risk_note: str = "如披露客户或供应商集中，建议查看风险章节。"
    evidence_refs: List[str] = []


class CapitalActionsBlock(BaseModel):
    dividends: List[dict] = []
    buybacks: List[dict] = []
    equity_incentives: List[dict] = []
    financing_actions: List[dict] = []
    summary: str = "未披露或无法确认。"
    evidence_refs: List[str] = []


class NonFinancialRisk(BaseModel):
    risk_name: str
    risk_type: str = "非财务风险"
    severity: str = "unknown"
    plain_explanation: str = ""
    source_type: str = "filing"
    evidence_refs: List[str] = []


class MissingInformation(BaseModel):
    field: str
    reason: str
    suggested_source: str = "公司公告或官方披露文件"


class AgentProfile(BaseModel):
    company_profile: CompanyProfileBlock
    business_model: BusinessModelBlock
    ownership: OwnershipBlock
    key_people: List[KeyPerson] = []
    industry_chain: IndustryChainBlock
    capital_actions: CapitalActionsBlock
    non_financial_risks: List[NonFinancialRisk] = []
    missing_information: List[MissingInformation] = []
    evidence_refs: List[str] = []


class AgentResult(BaseModel):
    profile: AgentProfile
    generation_meta: dict
    risk_facts: List[dict] = []
    risk_assessments: List[dict] = []
