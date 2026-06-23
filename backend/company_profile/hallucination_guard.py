from __future__ import annotations

from backend.company_profile.profile_schema import AgentProfile, MissingInformation


CRITICAL_FIELDS = [
    ("company_profile.main_business", "主营业务"),
    ("company_profile.controlling_shareholder", "控股股东"),
    ("company_profile.actual_controller", "实际控制人"),
]


class HallucinationGuard:
    def review(self, profile: AgentProfile, generation_meta: dict) -> tuple:
        missing = list(profile.missing_information)
        for path, label in CRITICAL_FIELDS:
            value = _value_at(profile, path)
            refs = _refs_for_path(profile, path)
            if _has_claim(value) and not refs:
                missing.append(
                    MissingInformation(
                        field=path,
                        reason="%s 缺少披露文件证据，已标记为待核验。" % label,
                        suggested_source="年报、招股说明书或交易所公告",
                    )
                )

        if not profile.key_people:
            missing.append(
                MissingInformation(
                    field="key_people",
                    reason="未从披露文件中确认关键人物履历。",
                    suggested_source="年报董监高章节、招股书董事监事高级管理人员章节",
                )
            )
        if not profile.non_financial_risks:
            missing.append(
                MissingInformation(
                    field="non_financial_risks",
                    reason="未从披露文件中确认非财务风险摘要。",
                    suggested_source="年报或招股书风险因素章节",
                )
            )

        profile.missing_information = _dedupe_missing(missing)
        generation_meta["missing_information_count"] = len(profile.missing_information)
        generation_meta["field_source_summary"] = {
            "filing_evidence_count": len(set(profile.evidence_refs)),
            "key_people_count": len(profile.key_people),
            "risk_count": len(profile.non_financial_risks),
            "has_business_evidence": bool(profile.business_model.evidence_refs),
            "has_ownership_evidence": bool(profile.ownership.evidence_refs),
        }
        generation_meta["confidence"] = _confidence(profile)
        return profile, generation_meta


def _value_at(profile: AgentProfile, path: str):
    current = profile
    for part in path.split("."):
        current = getattr(current, part)
    return current


def _refs_for_path(profile: AgentProfile, path: str):
    if path.startswith("company_profile."):
        return profile.company_profile.evidence_refs
    if path.startswith("business_model."):
        return profile.business_model.evidence_refs
    if path.startswith("ownership."):
        return profile.ownership.evidence_refs
    return []


def _has_claim(value) -> bool:
    return bool(value and str(value).strip() and str(value).strip() not in {"未披露", "无法确认", "未知"})


def _dedupe_missing(items):
    seen = set()
    deduped = []
    for item in items:
        key = (item.field, item.reason)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped[:16]


def _confidence(profile: AgentProfile) -> str:
    if len(profile.evidence_refs) >= 4 and len(profile.missing_information) <= 3:
        return "high"
    if len(profile.evidence_refs) >= 2 and len(profile.missing_information) <= 6:
        return "medium"
    return "low"
