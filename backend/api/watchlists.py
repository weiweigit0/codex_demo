from fastapi import APIRouter, Depends

from backend.api.deps import services
from backend.schemas.models import AlertRequest, WatchlistRequest

router = APIRouter(prefix="/api/watchlists", tags=["watchlists"])


@router.get("")
def list_watchlist(svc=Depends(services)):
    return {"items": svc.watchlist_service.list_watchlist()}


@router.post("")
def add_watchlist(request: WatchlistRequest, svc=Depends(services)):
    return svc.watchlist_service.add_company(request.company.dict())


@router.delete("/{company_id}")
def remove_watchlist(company_id: str, svc=Depends(services)):
    return {"deleted": svc.watchlist_service.remove_company(company_id)}


@router.get("/alerts")
def list_alerts(svc=Depends(services)):
    return {"items": svc.watchlist_service.list_alerts()}


@router.post("/alerts")
def add_alert(request: AlertRequest, svc=Depends(services)):
    return svc.watchlist_service.add_alert(request.dict())
