from fastapi import APIRouter, Depends, HTTPException, Request

from backend.three_minute_summary.schemas import CreateSummaryRequest, SummaryQuestionRequest


router = APIRouter(prefix="/api/three-minute-summaries", tags=["three-minute-summary"])


def orchestrator(request: Request):
    return request.app.state.three_minute_summary_orchestrator


def video_orchestrator(request: Request):
    return request.app.state.three_minute_video_orchestrator


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
