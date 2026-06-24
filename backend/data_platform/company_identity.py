from __future__ import annotations


class CompanyIdentityError(RuntimeError):
    """Raised when a company cannot safely be used with its market data source."""

    code = "COMPANY_IDENTITY_INCOMPLETE"
    retryable = True
    source = "company_identity"

    def __init__(self, message: str, missing_fields: list[str] | None = None):
        super().__init__(message)
        self.missing_fields = missing_fields or []


def missing_identity_fields(company: dict) -> list[str]:
    """Return the market-specific identifiers required by downstream sources."""
    market = (company.get("market") or "").upper()
    if market == "US":
        cik = str(company.get("cik") or "").strip()
        return [] if cik.isdigit() else ["cik"]
    if market == "CN":
        return [] if str(company.get("ticker") or "").strip() else ["ticker"]
    return ["market"]


def require_complete_identity(company: dict) -> dict:
    missing = missing_identity_fields(company)
    if not missing:
        return company
    market = (company.get("market") or "").upper()
    if market == "US":
        raise CompanyIdentityError(
            "美股公司缺少可用的 SEC CIK，无法读取 SEC 财务事实。",
            missing,
        )
    raise CompanyIdentityError("公司身份信息不完整，无法读取公开披露数据。", missing)
