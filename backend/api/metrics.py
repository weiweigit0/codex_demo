from fastapi import APIRouter

from backend.services.metric_dictionary import explain_metric, list_metrics

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


@router.get("/dictionary")
def metric_dictionary():
    return {"items": list_metrics()}


@router.get("/{metric_key}")
def metric_detail(metric_key: str):
    return explain_metric(metric_key)
