from fastapi import APIRouter, HTTPException

from backend.company_profile.orchestrator import CompanyProfileOrchestrator
from backend.company_profile.schemas import CreateProfileReportRequest, ProfileQaRequest


router = APIRouter(prefix="/api/company-profile", tags=["company-profile"])
orchestrator = CompanyProfileOrchestrator()


@router.post("/reports")
def create_report(request: CreateProfileReportRequest):
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="请输入公司名或股票代码")
    return orchestrator.create_report(
        query=request.query,
        market=request.market,
        document_type=request.document_type,
        year=request.year,
        report_style=request.report_style,
    )


@router.get("/tasks/{task_id}")
def get_task(task_id: str):
    try:
        return orchestrator.get_task(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/reports/{report_id}")
def get_report(report_id: str):
    try:
        return orchestrator.get_report(report_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/evidence/{evidence_id}")
def get_evidence(evidence_id: str):
    try:
        return orchestrator.get_evidence(evidence_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/reports/{report_id}/qa")
def profile_qa(report_id: str, request: ProfileQaRequest):
    try:
        return orchestrator.answer_question(report_id, request.question)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/reports/{report_id}/finance-handoff")
def finance_handoff(report_id: str, request: ProfileQaRequest):
    try:
        return orchestrator.finance_handoff(report_id, request.question)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
