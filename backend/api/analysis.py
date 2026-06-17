from fastapi import APIRouter, Depends, HTTPException

from backend.api.deps import services
from backend.schemas.models import AnalyzeRequest, IndustryCompareRequest
from backend.services.analysis_engine import analyze_periods

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


@router.post("/report-card")
def report_card(request: AnalyzeRequest, svc=Depends(services)):
    try:
        company = svc.company_service.resolve(request.ticker, request.market)
        dataset = svc.report_service.fetch_financial_dataset(
            company,
            periods=request.periods,
            period_type=request.period_type,
        )
        return analyze_periods(company, dataset, request.periods, request.period_type)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/period-comparison")
def period_comparison(request: AnalyzeRequest, svc=Depends(services)):
    return report_card(request, svc)


@router.post("/industry-comparison")
def industry_comparison(request: IndustryCompareRequest, svc=Depends(services)):
    try:
        return svc.industry_service.compare(
            ticker=request.ticker,
            market=request.market,
            period=request.period,
            peer_tickers=request.peer_tickers,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
