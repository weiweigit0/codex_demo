from fastapi import APIRouter, Depends, HTTPException

from backend.api.deps import services

router = APIRouter(prefix="/api/companies", tags=["companies"])


@router.get("/search")
def search_companies(q: str, market: str = "ALL", svc=Depends(services)):
    return {"items": svc.company_service.search(q, market)}


@router.get("/top")
def top_companies(market: str = "ALL", svc=Depends(services)):
    return {"items": svc.company_service.top(market)}


@router.get("/{market}/{ticker}")
def get_company(market: str, ticker: str, svc=Depends(services)):
    try:
        return {"company": svc.company_service.resolve(ticker, market)}
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc))
