from fastapi import APIRouter, HTTPException

from backend.support.catalog import SupportCatalog


router = APIRouter(prefix="/support-api", tags=["support-catalog"])
catalog = SupportCatalog()


@router.get("/companies")
def supported_companies(q: str = "", market: str = "ALL", limit: int = 200):
    try:
        return catalog.query(q=q, market=market, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"支持列表获取失败：{exc}")


@router.get("/top")
def top_supported_companies():
    try:
        return catalog.top()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"头部公司列表获取失败：{exc}")


@router.get("/coverage")
def support_coverage():
    try:
        return catalog.coverage()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"覆盖范围获取失败：{exc}")
