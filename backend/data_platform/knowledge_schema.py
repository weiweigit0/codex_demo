"""Canonical names shared by ingestion, finance and profile domains."""

OFFICIAL_FILING = "official_filing"
ENCYCLOPEDIA = "encyclopedia"
MODEL_DERIVED = "model_derived"

CONTENT_TYPES = {"paragraph", "table", "list", "metadata"}
QUALITY_STATUSES = {"validated", "needs_review", "extracted", "missing"}


def source_authority(source_type: str) -> str:
    if source_type in {"annual", "quarterly", "prospectus", "annual_report", "quarterly_report"}:
        return OFFICIAL_FILING
    if source_type in {"wikipedia", "baidu_baike", "encyclopedia"}:
        return ENCYCLOPEDIA
    return MODEL_DERIVED
