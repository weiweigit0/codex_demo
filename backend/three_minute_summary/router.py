import os

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from backend.three_minute_summary.schemas import CreateSummaryRequest, SummaryQuestionRequest


router = APIRouter(prefix="/api/three-minute-summaries", tags=["three-minute-summary"])


def orchestrator(request: Request):
    return request.app.state.three_minute_summary_orchestrator


def video_orchestrator(request: Request):
    return request.app.state.three_minute_video_orchestrator


def current_user(request: Request, authorization: str = Header(default="")):
    token = authorization[len("Bearer "):].strip() if authorization.startswith("Bearer ") else ""
    try:
        return request.app.state.services.auth_service.me(token)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="登录后才可申请视频生产。") from exc


@router.post("")
def create_summary(payload: CreateSummaryRequest, svc=Depends(orchestrator)):
    return svc.create_summary(payload.ticker, payload.market, payload.period_type, payload.period, payload.allow_web_enrichment)


@router.get("/tasks/{task_id}")
def get_task(task_id: str, svc=Depends(orchestrator)):
    try:
        return svc.get_task(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/{summary_id}")
def get_summary(summary_id: str, svc=Depends(orchestrator)):
    try:
        return svc.get_public_summary(summary_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/{summary_id}/questions")
def ask_question(summary_id: str, payload: SummaryQuestionRequest, svc=Depends(orchestrator)):
    try:
        return svc.answer_question(summary_id, payload.question)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/{summary_id}/video-scripts")
def create_video_script(summary_id: str, svc=Depends(video_orchestrator)):
    return svc.create_script(summary_id)


@router.get("/video-tasks/{task_id}")
def get_video_task(task_id: str, svc=Depends(video_orchestrator)):
    try:
        return svc.get_task(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/video-scripts/{script_id}")
def get_video_script(script_id: str, svc=Depends(video_orchestrator)):
    try:
        return svc.get_script(script_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/video-scripts/{script_id}/brief")
def export_video_brief(script_id: str, user=Depends(current_user), svc=Depends(video_orchestrator)):
    try:
        return {"brief": svc.export_brief(script_id, user), "media_url": os.getenv("MEDIA_PRODUCTION_URL", "http://localhost:8766").rstrip("/")}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
