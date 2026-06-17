from fastapi import APIRouter, Depends, HTTPException

from backend.api.deps import services

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("/options")
def report_options(ticker: str, market: str = "US", svc=Depends(services)):
    try:
        company = svc.company_service.resolve(ticker, market)
        periods = svc.report_service.list_options(company)
        return {"company": company, "periods": periods}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.get("/list")
def list_reports(ticker: str, market: str = "US", svc=Depends(services)):
    try:
        company = svc.company_service.resolve(ticker, market)
        options = svc.report_service.list_options(company)
        return {"company": company, "reports": options.get("reports", [])}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
